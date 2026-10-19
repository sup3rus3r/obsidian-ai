"""Merge -> GGUF conversion -> quantization -> Ollama registration pipeline.
Synchronous — called via run_in_executor from main.py, same offload
rationale as trainer.py. Writes into the same job_store._jobs dict as
trainer.py, keyed by export_id instead of training job_id — job_store's
functions are generic over the id string, so this works without changes
there."""

import logging
import os
import shutil
import subprocess
import tempfile
import zipfile

from . import job_store

logger = logging.getLogger(__name__)


def _unzip(zip_path: str, dest_dir: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _run_subprocess(args: list[str], step: str) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{step} failed (exit {result.returncode}): {result.stderr[-4000:]}")


def run_gguf_export(export_id: str, adapter_path: str, base_hf_model_id: str, quantization: str):
    try:
        job_store.update_job(export_id, status="merging")

        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        adapter_dir = tempfile.mkdtemp(prefix="gguf_adapter_")
        _unzip(adapter_path, adapter_dir)

        base_model = AutoModelForCausalLM.from_pretrained(base_hf_model_id, device_map="auto")
        tokenizer = AutoTokenizer.from_pretrained(base_hf_model_id)

        merged_model = PeftModel.from_pretrained(base_model, adapter_dir)
        merged_model = merged_model.merge_and_unload()

        merged_dir = tempfile.mkdtemp(prefix="gguf_merged_")
        merged_model.save_pretrained(merged_dir)
        tokenizer.save_pretrained(merged_dir)

        llamacpp_dir = os.environ["LLAMACPP_DIR"]

        job_store.update_job(export_id, status="converting_gguf")
        gguf_dir = tempfile.mkdtemp(prefix="gguf_out_")
        f16_gguf_path = os.path.join(gguf_dir, "model-f16.gguf")
        convert_script = os.path.join(llamacpp_dir, "convert_hf_to_gguf.py")
        _run_subprocess(
            ["python", convert_script, merged_dir, "--outfile", f16_gguf_path, "--outtype", "f16"],
            "GGUF conversion",
        )

        job_store.update_job(export_id, status="quantizing")
        quantized_gguf_path = os.path.join(gguf_dir, f"model-{quantization}.gguf")
        quantize_bin = os.path.join(llamacpp_dir, "llama-quantize")
        _run_subprocess(
            [quantize_bin, f16_gguf_path, quantized_gguf_path, quantization],
            "GGUF quantization",
        )

        gguf_size_bytes = os.path.getsize(quantized_gguf_path)
        job_store.update_job(export_id, gguf_size_bytes=gguf_size_bytes)

        ollama_model_tag = f"obsidian-ft-{export_id[:8]}:latest"
        modelfile_dir = tempfile.mkdtemp(prefix="gguf_modelfile_")
        modelfile_path = os.path.join(modelfile_dir, "Modelfile")
        # No ADAPTER line — Ollama v0.34+ removed that directive. The adapter
        # is already merged into the quantized GGUF above.
        with open(modelfile_path, "w") as f:
            f.write(f"FROM {quantized_gguf_path}\n")

        job_store.update_job(export_id, status="registering")
        _run_subprocess(
            ["ollama", "create", ollama_model_tag, "-f", modelfile_path],
            "Ollama model registration",
        )

        job_store.update_job(
            export_id,
            status="completed",
            gguf_path=quantized_gguf_path,
            ollama_model_tag=ollama_model_tag,
        )

        shutil.rmtree(adapter_dir, ignore_errors=True)
        shutil.rmtree(merged_dir, ignore_errors=True)

    except Exception as e:
        logger.exception("GGUF export %s failed", export_id)
        job_store.update_job(export_id, status="failed", error=str(e))
