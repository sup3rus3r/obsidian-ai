"""Client for the standalone inspector_service (see backend/inspector_service/)
— phase 2 local-model interpretability inspection. Unlike tunnel.py, this
module is read-only/detection-only: it never starts or stops the service.
A GPU-resident process holding multi-GB of model weights is much riskier
to auto-manage than a stateless ngrok proxy, so the user starts this
service themselves (same lifecycle expectation as running Ollama) — this
module only checks whether it's reachable and proxies job calls to it."""

import logging
import os

import httpx

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return os.getenv("INSPECTOR_SERVICE_URL", "http://localhost:8765").rstrip("/")


async def ping() -> dict:
    """Returns {reachable: bool, model_loaded: str | None}. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{_base_url()}/health")
            resp.raise_for_status()
            data = resp.json()
            return {"reachable": True, "model_loaded": data.get("model_loaded")}
    except Exception as e:
        logger.debug("Inspector service unreachable: %s", e)
        return {"reachable": False, "model_loaded": None}


async def trigger_inspection(hf_model_id: str, prompt: str, capture_config: dict) -> str:
    """Submit a capture job to the service. Returns the service's job_id.
    Raises on failure (unreachable service, bad request) — the caller
    (inspector_engine.py) is responsible for turning that into a failed
    InspectionRun status, not this client."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{_base_url()}/inspect", json={
            "hf_model_id": hf_model_id,
            "prompt": prompt,
            "capture_config": capture_config,
        })
        resp.raise_for_status()
        return resp.json()["job_id"]


async def poll_inspection(job_id: str) -> dict:
    """Returns the service's job status dict: {job_id, status, summary,
    has_artifact, error}."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_base_url()}/inspect/{job_id}")
        resp.raise_for_status()
        return resp.json()


async def download_artifact(job_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{_base_url()}/inspect/{job_id}/artifact")
        resp.raise_for_status()
        return resp.content


async def cancel_inspection(job_id: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(f"{_base_url()}/inspect/{job_id}/cancel")
        except Exception as e:
            logger.warning("Failed to cancel inspector job %s: %s", job_id, e)
