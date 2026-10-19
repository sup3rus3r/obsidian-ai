"""Client for the standalone finetune_service (see backend/finetune_service/)
— the local_wsl2 LoRA training backend, running inside a CUDA-enabled WSL2
distro. Same trust/lifecycle model as inspector_client.py: a GPU-resident
training process is risky to auto-manage from this process, so the user
starts/stops it themselves (same expectation as running Ollama). This
module only checks reachability and proxies job calls to it."""

import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return os.getenv("FINETUNE_SERVICE_URL", "http://localhost:8766").rstrip("/")


async def ping() -> dict:
    """Returns {reachable, gpu_available, vram_free_gb}. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{_base_url()}/health")
            resp.raise_for_status()
            data = resp.json()
            return {
                "reachable": True,
                "gpu_available": bool(data.get("gpu_available")),
                "vram_free_gb": data.get("vram_free_gb"),
            }
    except Exception as e:
        logger.debug("Finetune service unreachable: %s", e)
        return {"reachable": False, "gpu_available": False, "vram_free_gb": None}


async def trigger_finetune(base_hf_model_id: str, dataset_jsonl_bytes: bytes, hyperparams: dict) -> str:
    """Submit a training job to the service. Returns the service's job_id.
    Raises on failure (unreachable service, bad request) — the caller
    (finetune_engine.py) is responsible for turning that into a failed
    FineTuneRun status, not this client."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{_base_url()}/finetune", json={
            "base_hf_model_id": base_hf_model_id,
            "dataset_jsonl_b64": base64.b64encode(dataset_jsonl_bytes).decode("ascii"),
            "hyperparams": hyperparams,
        })
        resp.raise_for_status()
        return resp.json()["job_id"]


async def poll_finetune(job_id: str) -> dict:
    """Returns {status, progress: {...}, error}."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_base_url()}/finetune/{job_id}")
        resp.raise_for_status()
        return resp.json()


async def download_adapter(job_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(f"{_base_url()}/finetune/{job_id}/artifact")
        resp.raise_for_status()
        return resp.content


async def trigger_gguf_export(job_id: str, quantization: str) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{_base_url()}/finetune/{job_id}/export", json={
            "quantization": quantization,
        })
        resp.raise_for_status()
        return resp.json()["export_id"]


async def poll_gguf_export(export_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_base_url()}/finetune/export/{export_id}")
        resp.raise_for_status()
        return resp.json()


async def download_gguf(export_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.get(f"{_base_url()}/finetune/export/{export_id}/artifact")
        resp.raise_for_status()
        return resp.content


async def cancel_finetune(job_id: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(f"{_base_url()}/finetune/{job_id}/cancel")
        except Exception as e:
            logger.warning("Failed to cancel finetune job %s: %s", job_id, e)
