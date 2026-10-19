"""LoRA fine-tuning engine. Unlike inspector_engine.py, this never blocks a
background task waiting for job completion — a training run can take hours,
far longer than inspector_engine.py's capture pass. run_finetune_sqlite/
run_finetune_mongo only prepare the dataset, submit the job, and register a
scheduled poll (finetune_poller.py) before returning; the poller (not this
module) drives the run to completion across however many server restarts
that takes.
"""

import json
import logging
from datetime import datetime, timezone

import finetune_client
import finetune_dataset

logger = logging.getLogger(__name__)

_UNREACHABLE_ERROR = "Finetune service is not reachable. Start it separately — see backend/finetune_service/README.md."


def _hyperparams_from_json(hyperparams_json: str) -> dict:
    return json.loads(hyperparams_json) if hyperparams_json else {}


# ─── Core runner (SQLite) ───────────────────────────────────────────────────

async def run_finetune_sqlite(run_id: int, uploaded_bytes: bytes | None = None, uploaded_filename: str | None = None):
    """Background task: prepare the dataset, submit the training job,
    register the poller, return. Opens its own DB session — this always
    runs as a detached asyncio.create_task that outlives the HTTP request,
    same reasoning as inspector_engine.py's run_inspection_sqlite."""
    from database import SessionLocal
    from models import FineTuneRun
    from file_storage import FileStorageService

    db = SessionLocal()
    try:
        run = db.query(FineTuneRun).filter(FineTuneRun.id == run_id).first()
        if not run:
            return

        run.status = "preparing_dataset"
        db.commit()

        try:
            if run.dataset_source_type == "uploaded_file" and uploaded_bytes is not None:
                rows = finetune_dataset.parse_uploaded_dataset(uploaded_bytes, uploaded_filename or run.dataset_filename or "dataset.jsonl")
            else:
                session_ids = json.loads(run.dataset_session_ids_json) if run.dataset_session_ids_json else []
                rows = finetune_dataset.export_sessions_to_chatml(db, session_ids, is_mongo=False)

            if not rows:
                run.status = "failed"
                run.error = "Dataset is empty after preparation — nothing to train on."
                db.commit()
                return

            jsonl_bytes = finetune_dataset.rows_to_jsonl_bytes(rows)
            storage_path = FileStorageService.save_file_sqlite(f"finetune_{run_id}", "dataset.jsonl", jsonl_bytes)
            run.dataset_storage_path = storage_path
            run.dataset_row_count = len(rows)
            db.commit()
        except Exception as e:
            run.status = "failed"
            run.error = f"Failed to prepare dataset: {e}"
            db.commit()
            return

        run.status = "submitting"
        db.commit()

        hyperparams = _hyperparams_from_json(run.hyperparams_json)

        if run.compute_backend == "local_wsl2":
            status = await finetune_client.ping()
            if not status["reachable"]:
                run.status = "failed"
                run.error = _UNREACHABLE_ERROR
                db.commit()
                return
            try:
                job_id = await finetune_client.trigger_finetune(run.base_hf_model_id, jsonl_bytes, hyperparams)
            except Exception as e:
                run.status = "failed"
                run.error = f"Failed to start fine-tuning: {e}"
                db.commit()
                return
            run.wsl2_job_id = job_id
            run.status = "training"
        else:  # runpod
            import runpod_client
            try:
                runpod_job_id = await runpod_client.submit_job(run.base_hf_model_id, jsonl_bytes, hyperparams)
            except Exception as e:
                run.status = "failed"
                run.error = f"Failed to submit RunPod job: {e}"
                db.commit()
                return
            run.runpod_job_id = runpod_job_id
            run.status = "provisioning"

        run.started_training_at = datetime.now(timezone.utc)
        db.commit()

        _register_poller_sqlite(run_id)

    except Exception as e:
        logger.error("Finetune run %s failed: %s", run_id, e)
        try:
            run.status = "failed"
            run.error = str(e)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _register_poller_sqlite(run_id: int):
    from scheduler import scheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from finetune_poller import poll_finetune_run_sqlite
    scheduler.add_job(
        poll_finetune_run_sqlite,
        trigger=IntervalTrigger(seconds=20),
        args=[run_id],
        id=f"finetune_run_{run_id}",
        replace_existing=True,
    )


# ─── Core runner (MongoDB) ──────────────────────────────────────────────────

async def run_finetune_mongo(run_id: str, uploaded_bytes: bytes | None = None, uploaded_filename: str | None = None):
    """Mongo twin of run_finetune_sqlite — see its docstring."""
    from database_mongo import get_database
    from models_mongo import FineTuneRunCollection
    from file_storage import FileStorageService

    mongo_db = get_database()
    run = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
    if not run:
        return

    try:
        await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "preparing_dataset"})

        try:
            if run.get("dataset_source_type") == "uploaded_file" and uploaded_bytes is not None:
                rows = finetune_dataset.parse_uploaded_dataset(uploaded_bytes, uploaded_filename or run.get("dataset_filename") or "dataset.jsonl")
            else:
                session_ids = json.loads(run["dataset_session_ids_json"]) if run.get("dataset_session_ids_json") else []
                rows = await finetune_dataset.export_sessions_to_chatml_async(mongo_db, session_ids)

            if not rows:
                await FineTuneRunCollection.update_status(mongo_db, run_id, {
                    "status": "failed",
                    "error": "Dataset is empty after preparation — nothing to train on.",
                })
                return

            jsonl_bytes = finetune_dataset.rows_to_jsonl_bytes(rows)
            file_id = await FileStorageService.save_file_gridfs(mongo_db, "dataset.jsonl", jsonl_bytes, {"finetune_run_id": run_id})
            await FineTuneRunCollection.update_status(mongo_db, run_id, {
                "dataset_storage_path": file_id,
                "dataset_row_count": len(rows),
            })
        except Exception as e:
            await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": f"Failed to prepare dataset: {e}"})
            return

        await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "submitting"})

        hyperparams = _hyperparams_from_json(run.get("hyperparams_json"))
        updates = {}

        if run.get("compute_backend") == "local_wsl2":
            status = await finetune_client.ping()
            if not status["reachable"]:
                await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": _UNREACHABLE_ERROR})
                return
            try:
                job_id = await finetune_client.trigger_finetune(run["base_hf_model_id"], jsonl_bytes, hyperparams)
            except Exception as e:
                await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": f"Failed to start fine-tuning: {e}"})
                return
            updates["wsl2_job_id"] = job_id
            updates["status"] = "training"
        else:  # runpod
            import runpod_client
            try:
                runpod_job_id = await runpod_client.submit_job(run["base_hf_model_id"], jsonl_bytes, hyperparams)
            except Exception as e:
                await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": f"Failed to submit RunPod job: {e}"})
                return
            updates["runpod_job_id"] = runpod_job_id
            updates["status"] = "provisioning"

        updates["started_training_at"] = datetime.now(timezone.utc)
        await FineTuneRunCollection.update_status(mongo_db, run_id, updates)

        _register_poller_mongo(run_id)

    except Exception as e:
        logger.error("Finetune run %s (mongo) failed: %s", run_id, e)
        try:
            await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "failed", "error": str(e)})
        except Exception:
            pass


def _register_poller_mongo(run_id: str):
    from scheduler import scheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from finetune_poller import poll_finetune_run_mongo
    scheduler.add_job(
        poll_finetune_run_mongo,
        trigger=IntervalTrigger(seconds=20),
        args=[run_id],
        id=f"finetune_run_{run_id}",
        replace_existing=True,
    )


# ─── Cost estimate (pure function, no DB) ───────────────────────────────────

_ASSUMED_COST_PER_HOUR_USD = 1.39  # A100-class on-demand serverless rate assumption
_ASSUMED_SECONDS_PER_STEP = 2.0    # ~7-13B class model, A100-class GPU
_ASSUMED_GGUF_DISK_GB = 4.0        # ~7-13B class model, quantized GGUF


def estimate_cost(
    base_hf_model_id: str,
    dataset_row_count: int,
    hyperparams: dict,
    compute_backend: str,
    export_to_ollama: bool = False,
) -> dict:
    """Crude heuristic cost/time estimate — no DB access, no model
    inspection. Assumes a ~7-13B parameter class model and ~2s/training
    step on an A100-class GPU; actual cost for a much larger or smaller
    model, or a different GPU, will differ substantially. This is a rough
    planning number shown before a run starts, never a billing guarantee."""
    num_epochs = hyperparams.get("num_epochs", 3)
    per_device_batch_size = hyperparams.get("per_device_batch_size", 1)
    gradient_accumulation_steps = hyperparams.get("gradient_accumulation_steps", 8)

    effective_batch = max(1, per_device_batch_size * gradient_accumulation_steps)
    steps = max(1, (dataset_row_count * num_epochs) // effective_batch)
    estimated_minutes = steps * _ASSUMED_SECONDS_PER_STEP / 60

    estimated_usd = None
    if compute_backend == "runpod":
        estimated_usd = estimated_minutes / 60 * _ASSUMED_COST_PER_HOUR_USD

    disk_cost_gb = _ASSUMED_GGUF_DISK_GB if export_to_ollama else None

    caveat = (
        "Rough estimate only: assumes a ~7-13B parameter class base model and "
        "~2 seconds/training step on an A100-class GPU, not a measurement of "
        f"{base_hf_model_id!r} specifically. Actual time/cost can differ "
        "substantially for larger/smaller models or different hardware."
    )

    return {
        "estimated_usd": estimated_usd,
        "estimated_minutes": estimated_minutes,
        "disk_cost_gb": disk_cost_gb,
        "caveat": caveat,
    }


# ─── Auto-registration ──────────────────────────────────────────────────────

async def auto_register_from_run(db_or_mongo, run, is_mongo: bool = False):
    """Called by finetune_poller.py once ollama_model_tag is set on a
    completed run. Registers a new LLMProvider (reusing an existing ollama
    provider's base_url if the user already has one), and optionally a new
    Agent cloning the source agent's system_prompt. Handles both the
    SQLAlchemy ORM path (mutate run's attributes, caller commits) and the
    Mongo dict path (return updates dict, caller persists via
    FineTuneRunCollection.update_status) explicitly, since the two DBs'
    object shapes are incompatible at the call sites that use this."""
    if is_mongo:
        return await _auto_register_from_run_mongo(db_or_mongo, run)
    return _auto_register_from_run_sqlite(db_or_mongo, run)


def _auto_register_from_run_sqlite(db, run):
    from models import LLMProvider, Agent

    existing_ollama = db.query(LLMProvider).filter(
        LLMProvider.user_id == run.user_id,
        LLMProvider.provider_type == "ollama",
    ).first()
    base_url = existing_ollama.base_url if existing_ollama else "http://localhost:11434"

    provider = LLMProvider(
        user_id=run.user_id,
        name=f"Fine-tuned: {run.ollama_model_tag}",
        provider_type="ollama",
        base_url=base_url,
        model_id=run.ollama_model_tag,
        config_json=json.dumps({"source_finetune_run_id": run.id}),
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    run.created_provider_id = provider.id

    if run.auto_register_agent:
        source_agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
        agent = Agent(
            user_id=run.user_id,
            name=f"Fine-tuned: {run.ollama_model_tag}",
            description=f"Auto-registered from fine-tune run {run.id}",
            system_prompt=source_agent.system_prompt if source_agent else None,
            provider_id=provider.id,
            model_id=run.ollama_model_tag,
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        run.created_agent_id = agent.id


async def _auto_register_from_run_mongo(mongo_db, run: dict) -> dict:
    from models_mongo import LLMProviderCollection, AgentCollection

    existing = await mongo_db[LLMProviderCollection.collection_name].find_one({
        "user_id": run["user_id"],
        "provider_type": "ollama",
    })
    base_url = existing.get("base_url") if existing else "http://localhost:11434"

    provider_doc = {
        "user_id": run["user_id"],
        "name": f"Fine-tuned: {run.get('ollama_model_tag')}",
        "provider_type": "ollama",
        "base_url": base_url,
        "model_id": run.get("ollama_model_tag"),
        "config_json": json.dumps({"source_finetune_run_id": str(run["_id"])}),
    }
    created_provider = await LLMProviderCollection.create(mongo_db, provider_doc)
    updates = {"created_provider_id": str(created_provider["_id"])}

    if run.get("auto_register_agent"):
        source_agent = await AgentCollection.find_by_id(mongo_db, str(run["agent_id"]))
        agent_doc = {
            "user_id": run["user_id"],
            "name": f"Fine-tuned: {run.get('ollama_model_tag')}",
            "description": f"Auto-registered from fine-tune run {run['_id']}",
            "system_prompt": source_agent.get("system_prompt") if source_agent else None,
            "provider_id": str(created_provider["_id"]),
            "model_id": run.get("ollama_model_tag"),
        }
        created_agent = await AgentCollection.create(mongo_db, agent_doc)
        updates["created_agent_id"] = str(created_agent["_id"])

    return updates
