"""Standalone LoRA fine-tuning service — see finetune_service/pyproject.toml's
description for the full isolation rationale. Run with:
    uv run uvicorn app.main:app --host 0.0.0.0 --port 8766
from within backend/finetune_service/ (its own venv, not the main backend's).
"""

import asyncio
import base64
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import job_store, trainer, gguf_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Obsidian AI Finetune Service")


@app.get("/health")
async def health():
    gpu_available = False
    vram_free_gb = None
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            free_bytes, _total_bytes = torch.cuda.mem_get_info()
            vram_free_gb = free_bytes / (1024 ** 3)
    except Exception as e:
        logger.debug("torch unavailable or CUDA check failed: %s", e)

    response = {"status": "ok", "gpu_available": gpu_available}
    if gpu_available:
        response["vram_free_gb"] = vram_free_gb
    return response


class FinetuneRequest(BaseModel):
    base_hf_model_id: str
    dataset_jsonl_b64: str
    hyperparams: dict


@app.post("/finetune")
async def trigger_finetune(req: FinetuneRequest):
    job_id = job_store.create_job()
    job_store.update_job(job_id, base_hf_model_id=req.base_hf_model_id)
    dataset_bytes = base64.b64decode(req.dataset_jsonl_b64)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None,
        trainer.run_training_job,
        job_id,
        req.base_hf_model_id,
        dataset_bytes,
        req.hyperparams,
    )
    return {"job_id": job_id}


@app.get("/finetune/{job_id}")
async def get_finetune_job(job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/finetune/{job_id}/cancel")
async def cancel_finetune_job(job_id: str):
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_store.update_job(job_id, cancel_requested=True)
    return {"job_id": job_id, "cancel_requested": True}


@app.get("/finetune/{job_id}/artifact")
async def get_finetune_artifact(job_id: str):
    job = job_store.get_job(job_id)
    if not job or not job.get("adapter_path"):
        raise HTTPException(status_code=404, detail="No artifact for this job")
    return FileResponse(job["adapter_path"], media_type="application/zip")


class ExportRequest(BaseModel):
    quantization: str = "Q4_K_M"


@app.post("/finetune/{job_id}/export")
async def trigger_gguf_export(job_id: str, req: ExportRequest):
    job = job_store.get_job(job_id)
    if not job or not job.get("adapter_path"):
        raise HTTPException(status_code=404, detail="No completed training job with an adapter")

    export_id = job_store.create_job()
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None,
        gguf_pipeline.run_gguf_export,
        export_id,
        job["adapter_path"],
        job.get("base_hf_model_id", ""),
        req.quantization,
    )
    return {"export_id": export_id}


@app.get("/finetune/export/{export_id}")
async def get_gguf_export(export_id: str):
    job = job_store.get_job(export_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export not found")
    return job


@app.get("/finetune/export/{export_id}/artifact")
async def get_gguf_artifact(export_id: str):
    job = job_store.get_job(export_id)
    if not job or not job.get("gguf_path"):
        raise HTTPException(status_code=404, detail="No artifact for this export")
    return FileResponse(job["gguf_path"], media_type="application/octet-stream")
