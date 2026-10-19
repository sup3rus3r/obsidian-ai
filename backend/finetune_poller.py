"""Background poll executors for FineTuneRun records, run by APScheduler on
an interval. Must live in a top-level, importable module because APScheduler
serializes job references by dotted module path (e.g.
"finetune_poller.poll_finetune_run_sqlite"), same constraint as
async_job_poller.py.

Each poll opens its own fresh DB session, loads the run, and advances it
one step along its status machine (see models.py's FineTuneRun docstring
for the full status list). A run reaching any terminal status
(completed/failed/cancelled) deregisters its own scheduler job here, same
pattern as async_job_poller.py's _unschedule.
"""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
_RUNPOD_COST_PER_HOUR_USD = 1.39


def _unschedule(run_id):
    from scheduler import scheduler
    try:
        scheduler.remove_job(f"finetune_run_{run_id}")
    except Exception:
        pass


# ─── SQLite ─────────────────────────────────────────────────────────────────

async def poll_finetune_run_sqlite(run_id: int):
    from database import SessionLocal
    from models import FineTuneRun

    db = SessionLocal()
    try:
        run = db.query(FineTuneRun).filter(FineTuneRun.id == run_id).first()
        if not run or run.status in _TERMINAL_STATUSES:
            _unschedule(run_id)
            return

        if run.status == "cancelled":
            await _cancel_backend_job_sqlite(run)
            _unschedule(run_id)
            return

        if run.status in ("training", "provisioning"):
            await _poll_training_sqlite(db, run)
        elif run.status in ("merging", "converting_gguf", "quantizing"):
            await _poll_gguf_export_sqlite(db, run)
        elif run.status == "registering":
            await _finish_registering_sqlite(db, run)

        if run.status in _TERMINAL_STATUSES:
            _unschedule(run_id)
    except Exception as e:
        logger.error("Finetune poll for run %s failed: %s", run_id, e)
    finally:
        db.close()


async def _cancel_backend_job_sqlite(run):
    if run.compute_backend == "local_wsl2" and run.wsl2_job_id:
        import finetune_client
        await finetune_client.cancel_finetune(run.wsl2_job_id)
    elif run.compute_backend == "runpod" and run.runpod_job_id:
        import runpod_client
        await runpod_client.cancel_job(run.runpod_job_id)


async def _poll_training_sqlite(db, run):
    if run.compute_backend == "local_wsl2":
        import finetune_client
        job = await finetune_client.poll_finetune(run.wsl2_job_id)
        mapped_status = job.get("status", "training")
    else:
        import runpod_client
        job = await runpod_client.poll_job(run.runpod_job_id)
        mapped_status = job["status"]

    if job.get("progress"):
        run.progress_json = json.dumps(job["progress"])

    if mapped_status == "failed":
        run.status = "failed"
        run.error = job.get("error") or "Training failed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    if mapped_status == "cancelled":
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    if mapped_status != "completed":
        run.status = mapped_status
        db.commit()
        return

    # Training completed — download and store the adapter.
    try:
        if run.compute_backend == "local_wsl2":
            import finetune_client
            adapter_bytes = await finetune_client.download_adapter(run.wsl2_job_id)
        else:
            import runpod_client
            adapter_bytes = await runpod_client.download_artifact(job["adapter_url"])
    except Exception as e:
        run.status = "failed"
        run.error = f"Failed to download adapter: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    from file_storage import FileStorageService
    storage_path = FileStorageService.save_file_sqlite(f"finetune_{run.id}", "adapter.zip", adapter_bytes)
    run.adapter_storage_path = storage_path
    run.adapter_size_bytes = len(adapter_bytes)

    if run.compute_backend == "runpod" and run.started_training_at:
        now = datetime.now(timezone.utc)
        started = run.started_training_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        hours = (now - started).total_seconds() / 3600
        run.runpod_actual_cost_usd = hours * _RUNPOD_COST_PER_HOUR_USD

    if run.export_to_ollama:
        run.status = "merging"
    else:
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
    db.commit()


async def _poll_gguf_export_sqlite(db, run):
    import finetune_client

    export_id = run.wsl2_job_id if run.compute_backend == "local_wsl2" else run.runpod_job_id

    if run.status == "merging":
        try:
            new_export_id = await finetune_client.trigger_gguf_export(export_id, run.gguf_quantization or "Q4_K_M")
        except Exception as e:
            run.status = "failed"
            run.error = f"Failed to start GGUF export: {e}"
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return
        run.wsl2_job_id = new_export_id
        run.status = "converting_gguf"
        db.commit()
        return

    export_job_id = run.wsl2_job_id
    job = await finetune_client.poll_gguf_export(export_job_id)
    status = job.get("status", "converting_gguf")

    if status == "failed":
        run.status = "failed"
        run.error = job.get("error") or "GGUF export failed"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    if status != "completed":
        run.status = status if status in ("converting_gguf", "quantizing") else run.status
        db.commit()
        return

    try:
        gguf_bytes = await finetune_client.download_gguf(export_job_id)
    except Exception as e:
        run.status = "failed"
        run.error = f"Failed to download GGUF artifact: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return

    from file_storage import FileStorageService
    storage_path = FileStorageService.save_file_sqlite(f"finetune_{run.id}", "model.gguf", gguf_bytes)
    run.merged_gguf_storage_path = storage_path
    run.merged_gguf_size_bytes = len(gguf_bytes)
    run.ollama_model_tag = job.get("ollama_model_tag")
    run.status = "registering"
    db.commit()


async def _finish_registering_sqlite(db, run):
    from finetune_engine import auto_register_from_run
    try:
        await auto_register_from_run(db, run, is_mongo=False)
    except Exception as e:
        run.status = "failed"
        run.error = f"Auto-registration failed: {e}"
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        return
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    db.commit()


# ─── MongoDB ────────────────────────────────────────────────────────────────

async def poll_finetune_run_mongo(run_id: str):
    from database_mongo import get_database
    from models_mongo import FineTuneRunCollection

    mongo_db = get_database()
    run = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
    if not run or run.get("status") in _TERMINAL_STATUSES:
        _unschedule(run_id)
        return

    try:
        if run.get("status") == "cancelled":
            await _cancel_backend_job_mongo(run)
            _unschedule(run_id)
            return

        status = run.get("status")
        if status in ("training", "provisioning"):
            await _poll_training_mongo(mongo_db, run_id, run)
        elif status in ("merging", "converting_gguf", "quantizing"):
            await _poll_gguf_export_mongo(mongo_db, run_id, run)
        elif status == "registering":
            await _finish_registering_mongo(mongo_db, run_id, run)

        updated = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
        if updated and updated.get("status") in _TERMINAL_STATUSES:
            _unschedule(run_id)
    except Exception as e:
        logger.error("Finetune poll (mongo) for run %s failed: %s", run_id, e)


async def _cancel_backend_job_mongo(run):
    if run.get("compute_backend") == "local_wsl2" and run.get("wsl2_job_id"):
        import finetune_client
        await finetune_client.cancel_finetune(run["wsl2_job_id"])
    elif run.get("compute_backend") == "runpod" and run.get("runpod_job_id"):
        import runpod_client
        await runpod_client.cancel_job(run["runpod_job_id"])


async def _poll_training_mongo(mongo_db, run_id, run):
    from models_mongo import FineTuneRunCollection

    if run.get("compute_backend") == "local_wsl2":
        import finetune_client
        job = await finetune_client.poll_finetune(run["wsl2_job_id"])
        mapped_status = job.get("status", "training")
    else:
        import runpod_client
        job = await runpod_client.poll_job(run["runpod_job_id"])
        mapped_status = job["status"]

    updates = {}
    if job.get("progress"):
        updates["progress_json"] = json.dumps(job["progress"])

    if mapped_status == "failed":
        updates["status"] = "failed"
        updates["error"] = job.get("error") or "Training failed"
        updates["completed_at"] = datetime.now(timezone.utc)
        await FineTuneRunCollection.update_status(mongo_db, run_id, updates)
        return

    if mapped_status == "cancelled":
        updates["status"] = "cancelled"
        updates["completed_at"] = datetime.now(timezone.utc)
        await FineTuneRunCollection.update_status(mongo_db, run_id, updates)
        return

    if mapped_status != "completed":
        updates["status"] = mapped_status
        await FineTuneRunCollection.update_status(mongo_db, run_id, updates)
        return

    try:
        if run.get("compute_backend") == "local_wsl2":
            import finetune_client
            adapter_bytes = await finetune_client.download_adapter(run["wsl2_job_id"])
        else:
            import runpod_client
            adapter_bytes = await runpod_client.download_artifact(job["adapter_url"])
    except Exception as e:
        updates["status"] = "failed"
        updates["error"] = f"Failed to download adapter: {e}"
        updates["completed_at"] = datetime.now(timezone.utc)
        await FineTuneRunCollection.update_status(mongo_db, run_id, updates)
        return

    from file_storage import FileStorageService
    file_id = await FileStorageService.save_file_gridfs(mongo_db, "adapter.zip", adapter_bytes, {"finetune_run_id": run_id})
    updates["adapter_storage_path"] = file_id
    updates["adapter_size_bytes"] = len(adapter_bytes)

    if run.get("compute_backend") == "runpod" and run.get("started_training_at"):
        now = datetime.now(timezone.utc)
        started = run["started_training_at"]
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        hours = (now - started).total_seconds() / 3600
        updates["runpod_actual_cost_usd"] = hours * _RUNPOD_COST_PER_HOUR_USD

    if run.get("export_to_ollama"):
        updates["status"] = "merging"
    else:
        updates["status"] = "completed"
        updates["completed_at"] = datetime.now(timezone.utc)
    await FineTuneRunCollection.update_status(mongo_db, run_id, updates)


async def _poll_gguf_export_mongo(mongo_db, run_id, run):
    from models_mongo import FineTuneRunCollection
    import finetune_client

    export_job_id = run.get("wsl2_job_id") if run.get("compute_backend") == "local_wsl2" else run.get("runpod_job_id")

    if run.get("status") == "merging":
        try:
            new_export_id = await finetune_client.trigger_gguf_export(export_job_id, run.get("gguf_quantization") or "Q4_K_M")
        except Exception as e:
            await FineTuneRunCollection.update_status(mongo_db, run_id, {
                "status": "failed", "error": f"Failed to start GGUF export: {e}", "completed_at": datetime.now(timezone.utc),
            })
            return
        await FineTuneRunCollection.update_status(mongo_db, run_id, {
            "wsl2_job_id": new_export_id, "status": "converting_gguf",
        })
        return

    job = await finetune_client.poll_gguf_export(run.get("wsl2_job_id"))
    status = job.get("status", "converting_gguf")

    if status == "failed":
        await FineTuneRunCollection.update_status(mongo_db, run_id, {
            "status": "failed", "error": job.get("error") or "GGUF export failed", "completed_at": datetime.now(timezone.utc),
        })
        return

    if status != "completed":
        if status in ("converting_gguf", "quantizing"):
            await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": status})
        return

    try:
        gguf_bytes = await finetune_client.download_gguf(run.get("wsl2_job_id"))
    except Exception as e:
        await FineTuneRunCollection.update_status(mongo_db, run_id, {
            "status": "failed", "error": f"Failed to download GGUF artifact: {e}", "completed_at": datetime.now(timezone.utc),
        })
        return

    from file_storage import FileStorageService
    file_id = await FileStorageService.save_file_gridfs(mongo_db, "model.gguf", gguf_bytes, {"finetune_run_id": run_id})
    await FineTuneRunCollection.update_status(mongo_db, run_id, {
        "merged_gguf_storage_path": file_id,
        "merged_gguf_size_bytes": len(gguf_bytes),
        "ollama_model_tag": job.get("ollama_model_tag"),
        "status": "registering",
    })


async def _finish_registering_mongo(mongo_db, run_id, run):
    from finetune_engine import auto_register_from_run
    from models_mongo import FineTuneRunCollection
    try:
        updates = await auto_register_from_run(mongo_db, run, is_mongo=True)
    except Exception as e:
        await FineTuneRunCollection.update_status(mongo_db, run_id, {
            "status": "failed", "error": f"Auto-registration failed: {e}", "completed_at": datetime.now(timezone.utc),
        })
        return
    updates["status"] = "completed"
    updates["completed_at"] = datetime.now(timezone.utc)
    await FineTuneRunCollection.update_status(mongo_db, run_id, updates)
