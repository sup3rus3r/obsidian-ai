"""LoRA/QLoRA training loop. Synchronous — called via
asyncio.get_event_loop().run_in_executor from main.py, since both model
loading and trainer.train() block on GPU compute for a long time (same
executor-offload pattern as inspector_service/app/capture.py, just with a
much longer-running call)."""

import json
import logging
import os
import shutil
import tempfile
import zipfile

from . import job_store

logger = logging.getLogger(__name__)


def _build_dataset(dataset_jsonl_bytes: bytes, tokenizer, max_seq_len: int):
    from datasets import Dataset

    rows = []
    for line in dataset_jsonl_bytes.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        text = tokenizer.apply_chat_template(obj["messages"], tokenize=False)
        rows.append({"text": text})

    return Dataset.from_list(rows)


def _zip_dir(src_dir: str, zip_path: str) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(src_dir):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, src_dir))


def run_training_job(job_id: str, base_hf_model_id: str, dataset_jsonl_bytes: bytes, hyperparams: dict):
    try:
        job_store.update_job(job_id, status="loading_model")

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainerCallback
        from peft import LoraConfig, get_peft_model
        from trl import SFTConfig, SFTTrainer

        quantization = hyperparams.get("quantization", "4bit")
        load_in_4bit = quantization == "4bit"
        load_in_8bit = quantization == "8bit"

        tokenizer = AutoTokenizer.from_pretrained(base_hf_model_id)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        model = AutoModelForCausalLM.from_pretrained(
            base_hf_model_id,
            load_in_4bit=load_in_4bit,
            load_in_8bit=load_in_8bit,
            device_map="auto",
        )

        lora_config = LoraConfig(
            r=hyperparams.get("lora_r", 16),
            lora_alpha=hyperparams.get("lora_alpha", 32),
            lora_dropout=hyperparams.get("lora_dropout", 0.05),
            target_modules=hyperparams.get("target_modules", ["q_proj", "v_proj"]),
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)

        job_store.update_job(job_id, status="preparing_dataset")
        dataset = _build_dataset(dataset_jsonl_bytes, tokenizer, hyperparams.get("max_seq_len", 1024))

        class _ProgressCallback(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                job_store.update_job(job_id, progress={
                    "current_step": state.global_step,
                    "total_steps": state.max_steps,
                    "current_epoch": int(state.epoch) if state.epoch is not None else None,
                    "total_epochs": int(args.num_train_epochs),
                    "loss": (logs or {}).get("loss"),
                })

            def on_step_end(self, args, state, control, **kwargs):
                job = job_store.get_job(job_id) or {}
                if job.get("cancel_requested"):
                    control.should_training_stop = True
                return control

        sft_config = SFTConfig(
            output_dir=tempfile.mkdtemp(prefix="finetune_train_"),
            per_device_train_batch_size=hyperparams.get("per_device_batch_size", 1),
            gradient_accumulation_steps=hyperparams.get("gradient_accumulation_steps", 8),
            learning_rate=hyperparams.get("learning_rate", 2e-4),
            num_train_epochs=hyperparams.get("num_epochs", 3),
            max_seq_length=hyperparams.get("max_seq_len", 1024),
            seed=hyperparams.get("seed", 42),
            logging_steps=1,
            save_strategy="no",
            report_to=[],
        )

        trainer = SFTTrainer(
            model=model,
            args=sft_config,
            train_dataset=dataset,
            processing_class=tokenizer,
            callbacks=[_ProgressCallback()],
        )

        job_store.update_job(job_id, status="training")
        trainer.train()

        job = job_store.get_job(job_id) or {}
        if job.get("cancel_requested"):
            job_store.update_job(job_id, status="cancelled")
            return

        adapter_dir = tempfile.mkdtemp(prefix="finetune_adapter_")
        model.save_pretrained(adapter_dir)
        tokenizer.save_pretrained(adapter_dir)

        zip_path = adapter_dir.rstrip(os.sep) + ".zip"
        _zip_dir(adapter_dir, zip_path)
        shutil.rmtree(adapter_dir, ignore_errors=True)

        job_store.update_job(job_id, status="completed", adapter_path=zip_path)

    except Exception as e:
        logger.exception("Training job %s failed", job_id)
        job_store.update_job(job_id, status="failed", error=str(e))
