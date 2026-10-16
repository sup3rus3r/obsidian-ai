"""Phase 2 of model auditing: local-model interpretability inspection engine.

Unlike auditor_engine.py (phase 1, black-box, calls LLM providers directly),
this engine never talks to an LLM provider itself — it makes HTTP calls to
the separate inspector_service (own process/venv, holds the real HF weights
and GPU memory) via inspector_client.py, polls it, and persists the result.

This is NOT solving interpretability. The numbers captured here (attention
entropy, residual-stream norms, logit-lens top-k projections) are real, but:
- Attention weight is not causation — it shows where probability mass was
  routed on that one forward pass, not what "caused" the output.
- Logit lens assumes every layer's residual stream lives in the final
  layer's basis ("basis drift" is a documented failure mode) — treat results
  as "what this specific linear projection suggests," not the model's belief.
- Single-neuron-level activations are not presumed interpretable features
  (Anthropic's superposition/monosemanticity research: networks routinely
  pack multiple unrelated concepts into one neuron when features are sparse
  — this engine never surfaces raw per-neuron values as if they were clean
  concepts).
- A single prompt's run is not a general statement about the model.
- This is not a safety or deception detector.
See models.py's InspectionRun docstring and the Inspector page's limits
banner for the full framing shown to the user.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import inspector_client

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 2.0
_MAX_POLL_ATTEMPTS = 600  # ~20 minutes ceiling — model load + capture should be well under this


async def _wait_for_job(job_id: str, is_cancelled) -> dict:
    """Poll inspector_service until the job finishes, or `is_cancelled()`
    (an async callable checking the InspectionRun's own DB status) returns
    True. Returns the final job status dict."""
    for _ in range(_MAX_POLL_ATTEMPTS):
        if await is_cancelled():
            await inspector_client.cancel_inspection(job_id)
            return {"status": "cancelled"}
        job = await inspector_client.poll_inspection(job_id)
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        await asyncio.sleep(_POLL_INTERVAL_S)
    return {"status": "failed", "error": "Inspection timed out waiting for the inspector service"}


def _build_capture_config(capture_config: dict) -> dict:
    return {
        "layers": capture_config.get("layers"),
        "capture_attention": capture_config.get("capture_attention", True),
        "capture_residual": capture_config.get("capture_residual", True),
        "logit_lens_topk": capture_config.get("logit_lens_topk", 5),
        "max_seq_len": capture_config.get("max_seq_len", 256),
    }


# ─── Core runner (SQLite) ───────────────────────────────────────────────────

async def run_inspection_sqlite(run_id: int):
    """Background task: trigger the inspector service, poll it, persist
    results. Opens its own DB session — see eval_engine.py's
    run_eval_suite_sqlite docstring for why (this always runs as a detached
    asyncio.create_task that outlives the HTTP request)."""
    from models import InspectionRun
    from database import SessionLocal
    from file_storage import FileStorageService

    db = SessionLocal()
    try:
        run = db.query(InspectionRun).filter(InspectionRun.id == run_id).first()
        if not run:
            return

        async def is_cancelled() -> bool:
            db.expire(run)
            db.refresh(run)
            return run.status == "cancelled"

        status = (await inspector_client.ping())
        if not status["reachable"]:
            run.status = "failed"
            run.error = "Inspector service is not reachable. Start it separately — see backend/inspector_service/README.md."
            db.commit()
            return

        run.status = "loading_model"
        db.commit()

        capture_config = json.loads(run.capture_config_json) if run.capture_config_json else {}
        try:
            job_id = await inspector_client.trigger_inspection(run.hf_model_id, run.prompt, _build_capture_config(capture_config))
        except Exception as e:
            run.status = "failed"
            run.error = f"Failed to start inspection: {e}"
            db.commit()
            return

        run.status = "capturing"
        db.commit()

        job = await _wait_for_job(job_id, is_cancelled)

        if job["status"] == "cancelled":
            run.status = "cancelled"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        if job["status"] == "failed":
            run.status = "failed"
            run.error = job.get("error") or "Inspection failed"
            db.commit()
            return

        run.status = "processing"
        db.commit()

        run.summary_json = json.dumps(job.get("summary") or {})

        if job.get("has_artifact"):
            try:
                artifact_bytes = await inspector_client.download_artifact(job_id)
                storage_path = FileStorageService.save_file_sqlite(f"inspection_{run_id}", f"{job_id}.safetensors", artifact_bytes)
                run.artifact_storage_path = storage_path
            except Exception as e:
                logger.warning("Failed to download/store inspection artifact for run %s: %s", run_id, e)

        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        logger.error("Inspection run %s failed: %s", run_id, e)
        try:
            run.status = "failed"
            run.error = str(e)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ─── Core runner (MongoDB) ──────────────────────────────────────────────────

async def run_inspection_mongo(run_id: str):
    """Mongo twin of run_inspection_sqlite — see its docstring."""
    from database_mongo import get_database
    from models_mongo import InspectionRunCollection
    from file_storage import FileStorageService

    mongo_db = get_database()

    run = await InspectionRunCollection.find_by_id(mongo_db, run_id)
    if not run:
        return

    try:
        async def is_cancelled() -> bool:
            current = await InspectionRunCollection.find_by_id(mongo_db, run_id)
            return bool(current and current.get("status") == "cancelled")

        status = (await inspector_client.ping())
        if not status["reachable"]:
            await InspectionRunCollection.update_status(mongo_db, run_id, {
                "status": "failed",
                "error": "Inspector service is not reachable. Start it separately — see backend/inspector_service/README.md.",
            })
            return

        await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "loading_model"})

        capture_config_raw = run.get("capture_config_json")
        capture_config = json.loads(capture_config_raw) if capture_config_raw else {}
        try:
            job_id = await inspector_client.trigger_inspection(run["hf_model_id"], run["prompt"], _build_capture_config(capture_config))
        except Exception as e:
            await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": f"Failed to start inspection: {e}"})
            return

        await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "capturing"})

        job = await _wait_for_job(job_id, is_cancelled)

        if job["status"] == "cancelled":
            await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "cancelled", "completed_at": datetime.now(timezone.utc)})
            return

        if job["status"] == "failed":
            await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": job.get("error") or "Inspection failed"})
            return

        await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "processing"})

        updates = {"summary_json": json.dumps(job.get("summary") or {})}

        if job.get("has_artifact"):
            try:
                artifact_bytes = await inspector_client.download_artifact(job_id)
                file_id = await FileStorageService.save_file_gridfs(
                    mongo_db, f"{job_id}.safetensors", artifact_bytes, {"inspection_run_id": run_id},
                )
                updates["artifact_storage_path"] = file_id
            except Exception as e:
                logger.warning("Failed to download/store inspection artifact for run %s: %s", run_id, e)

        updates["status"] = "completed"
        updates["completed_at"] = datetime.now(timezone.utc)
        await InspectionRunCollection.update_status(mongo_db, run_id, updates)

    except Exception as e:
        logger.error("Inspection run %s (mongo) failed: %s", run_id, e)
        try:
            await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": str(e)})
        except Exception:
            pass
