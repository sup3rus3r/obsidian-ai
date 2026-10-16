"""Standalone inspection service — see inspector_service/pyproject.toml's
description for the full isolation rationale. Run with:
    uv run uvicorn app.main:app --port 8765
from within backend/inspector_service/ (its own venv, not the main backend's).

This service holds no opinions about interpretability claims — it returns
raw numbers (logit-lens projections, attention entropy, residual norms).
The "what this can/cannot validly claim" framing lives in the main
backend's inspector_engine.py / frontend limits banner, consumed by a
human, not asserted here.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import capture

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Obsidian AI Inspector Service")

_jobs: dict[str, dict] = {}
_artifact_dir = None  # set on startup, a temp dir for safetensors blobs


@app.on_event("startup")
async def _startup():
    global _artifact_dir
    import tempfile
    _artifact_dir = tempfile.mkdtemp(prefix="inspector_artifacts_")
    logger.info("Artifact dir: %s", _artifact_dir)


class CaptureConfig(BaseModel):
    layers: Optional[list[int]] = None  # None = all layers (summary stats only; full tensors need explicit layers)
    capture_attention: bool = True
    capture_residual: bool = True
    logit_lens_topk: int = 5
    max_seq_len: int = 256


class InspectRequest(BaseModel):
    hf_model_id: str
    prompt: str
    capture_config: CaptureConfig = CaptureConfig()


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": capture.get_loaded_model_id()}


async def _run_job(job_id: str, req: InspectRequest):
    _jobs[job_id]["status"] = "loading_model"
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            capture.run_capture,
            req.hf_model_id,
            req.prompt,
            req.capture_config.layers,
            req.capture_config.capture_attention,
            req.capture_config.capture_residual,
            req.capture_config.logit_lens_topk,
            req.capture_config.max_seq_len,
        )

        full_tensors = result.pop("_full_tensors", {})
        artifact_path = None
        if full_tensors:
            artifact_path = _save_artifact(job_id, full_tensors)

        _jobs[job_id].update({
            "status": "completed",
            "summary": result,
            "artifact_path": artifact_path,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.exception("Inspection job %s failed", job_id)
        _jobs[job_id].update({"status": "failed", "error": str(e)})


def _save_artifact(job_id: str, full_tensors: dict) -> str:
    from safetensors.torch import save_file
    import os

    flat = {}
    for layer_idx, tensors in full_tensors.items():
        for name, tensor in tensors.items():
            flat[f"layer_{layer_idx}_{name}"] = tensor.contiguous()

    path = os.path.join(_artifact_dir, f"{job_id}.safetensors")
    save_file(flat, path)
    return path


@app.post("/inspect")
async def trigger_inspect(req: InspectRequest):
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "pending", "created_at": time.time()}
    asyncio.ensure_future(_run_job(job_id, req))
    return {"job_id": job_id, "status": "pending"}


@app.get("/inspect/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "summary": job.get("summary"),
        "has_artifact": job.get("artifact_path") is not None,
        "error": job.get("error"),
    }


@app.get("/inspect/{job_id}/artifact")
async def get_artifact(job_id: str):
    job = _jobs.get(job_id)
    if not job or not job.get("artifact_path"):
        raise HTTPException(status_code=404, detail="No artifact for this job")
    return FileResponse(job["artifact_path"], media_type="application/octet-stream")


@app.post("/inspect/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Best-effort: marks the job cancelled so the main backend's poller
    stops waiting on it. Does not interrupt an in-flight forward pass (a
    single capture pass is short — see the plan's latency estimates — so
    this is acceptable; cancellation matters more for queued jobs)."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] in ("completed", "failed"):
        raise HTTPException(status_code=400, detail="Job already finished")
    job["status"] = "cancelled"
    return {"job_id": job_id, "status": "cancelled"}
