"""Client for RunPod's serverless endpoint API — the 'runpod' compute_backend
for LoRA fine-tuning. Requires a pre-built/pushed RunPod serverless handler
image (out of scope for this repo — the handler itself is not part of this
codebase, only the client that calls it).

Expected handler request payload (the {"input": {...}} body of a RunPod
/run call):
    {
        "base_hf_model_id": str,
        "dataset_jsonl_b64": str,   # base64-encoded ChatML JSONL
        "hyperparams": dict,        # same shape as FineTuneHyperparams
    }

Expected handler response payload (RunPod's "output" field once the job
reaches COMPLETED):
    {
        "adapter_url": str,   # presigned S3 URL to the zipped LoRA adapter
    }

The RunPod API key is resolved via the 'runpod_api_key_secret_id' app
setting -> UserSecret.encrypted_value, decrypted with the same global
Fernet helper (encryption.decrypt_api_key) used everywhere else in this
codebase for background-worker-path decryption (no per-request user_id
available here, same reasoning as async_job_poller.py's decrypt calls).
The endpoint id comes from the 'runpod_endpoint_id' app setting.
"""

import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_RUNPOD_API_BASE = "https://api.runpod.ai/v2"

# RunPod status -> this feature's internal status vocabulary
_STATUS_MAP = {
    "IN_QUEUE": "provisioning",
    "IN_PROGRESS": "training",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
    "TIMED_OUT": "failed",
}


async def _get_credentials() -> tuple[str, str]:
    """Returns (api_key, endpoint_id). Raises RuntimeError with a clear
    message if either setting is missing — the caller (finetune_engine.py)
    turns that into a failed FineTuneRun, same pattern as the local_wsl2
    unreachable-service path."""
    from config import DATABASE_TYPE
    from encryption import decrypt_api_key

    if DATABASE_TYPE == "mongo":
        from database_mongo import get_database
        from models_mongo import AppSettingCollection
        mongo_db = get_database()
        secret_id = await AppSettingCollection.get(mongo_db, "runpod_api_key_secret_id")
        endpoint_id = await AppSettingCollection.get(mongo_db, "runpod_endpoint_id")
        if not secret_id or not endpoint_id:
            raise RuntimeError("RunPod is not configured — set it under Settings > Fine-Tuning first.")
        from models_mongo import UserSecretCollection
        secret = await UserSecretCollection.find_by_id(mongo_db, secret_id)
        if not secret:
            raise RuntimeError("RunPod API key secret no longer exists — reconfigure it under Settings > Fine-Tuning.")
        api_key = decrypt_api_key(secret["encrypted_value"])
        return api_key, endpoint_id

    from database import SessionLocal
    from models import AppSetting, UserSecret
    db = SessionLocal()
    try:
        secret_id_row = db.query(AppSetting).filter(AppSetting.key == "runpod_api_key_secret_id").first()
        endpoint_id_row = db.query(AppSetting).filter(AppSetting.key == "runpod_endpoint_id").first()
        if not secret_id_row or not secret_id_row.value or not endpoint_id_row or not endpoint_id_row.value:
            raise RuntimeError("RunPod is not configured — set it under Settings > Fine-Tuning first.")
        secret = db.query(UserSecret).filter(UserSecret.id == int(secret_id_row.value)).first()
        if not secret:
            raise RuntimeError("RunPod API key secret no longer exists — reconfigure it under Settings > Fine-Tuning.")
        api_key = decrypt_api_key(secret.encrypted_value)
        return api_key, endpoint_id_row.value
    finally:
        db.close()


async def submit_job(base_hf_model_id: str, dataset_jsonl_bytes: bytes, hyperparams: dict) -> str:
    """Submits a training job to the RunPod serverless endpoint. Returns
    the RunPod job id. Raises on failure."""
    import base64
    api_key, endpoint_id = await _get_credentials()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{_RUNPOD_API_BASE}/{endpoint_id}/run",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": {
                "base_hf_model_id": base_hf_model_id,
                "dataset_jsonl_b64": base64.b64encode(dataset_jsonl_bytes).decode("ascii"),
                "hyperparams": hyperparams,
            }},
        )
        resp.raise_for_status()
        return resp.json()["id"]


async def poll_job(runpod_job_id: str) -> dict:
    """Returns {status, progress, error, adapter_url}. status is mapped to
    this feature's internal vocabulary via _STATUS_MAP."""
    api_key, endpoint_id = await _get_credentials()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{_RUNPOD_API_BASE}/{endpoint_id}/status/{runpod_job_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()

    runpod_status = data.get("status", "")
    status = _STATUS_MAP.get(runpod_status, "training")
    output = data.get("output") or {}
    return {
        "status": status,
        "progress": output.get("progress") if isinstance(output, dict) else None,
        "error": data.get("error"),
        "adapter_url": output.get("adapter_url") if isinstance(output, dict) else None,
    }


async def download_artifact(presigned_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.get(presigned_url)
        resp.raise_for_status()
        return resp.content


async def cancel_job(runpod_job_id: str) -> None:
    try:
        api_key, endpoint_id = await _get_credentials()
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{_RUNPOD_API_BASE}/{endpoint_id}/cancel/{runpod_job_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except Exception as e:
        logger.warning("Failed to cancel RunPod job %s: %s", runpod_job_id, e)
