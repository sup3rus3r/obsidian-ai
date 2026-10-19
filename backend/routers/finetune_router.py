"""LoRA Fine-Tuning router. See models.py's FineTuneRun docstring and
finetune_engine.py for the full rationale — training itself never runs in
this process; this router only creates the DB row and fires the detached
background task that prepares the dataset, submits the job, and registers
the poller."""

import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import FineTuneRun, Agent
from schemas import (
    TriggerFineTuneRequest,
    FineTuneRunResponse,
    FineTuneRunListResponse,
    FineTuneHyperparams,
    FineTuneProgress,
    FineTuneCostEstimateResponse,
)
from auth import get_current_user, TokenData
from file_storage import FileStorageService
import finetune_client

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import FineTuneRunCollection

router = APIRouter(prefix="/finetune", tags=["finetune"])


# ─── Inline request schema for the cost-estimate endpoint ───────────────────
# No dedicated request schema was pre-built for this one endpoint in
# schemas.py (only the response schema was) — adding it there, next to the
# other FineTune schemas, follows that file's existing convention of
# grouping request/response pairs together.

class FineTuneCostEstimateRequest(BaseModel):
    agent_id: Optional[Union[int, str]] = None
    base_hf_model_id: str
    dataset_row_count: int
    hyperparams: FineTuneHyperparams = FineTuneHyperparams()
    compute_backend: str
    export_to_ollama: bool = False


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_progress(progress_json: str | None) -> FineTuneProgress | None:
    if not progress_json:
        return None
    try:
        return FineTuneProgress(**json.loads(progress_json))
    except Exception:
        return None


def _run_to_response(run, is_mongo=False) -> FineTuneRunResponse:
    if is_mongo:
        hyperparams_raw = run.get("hyperparams_json")
        hyperparams = FineTuneHyperparams(**json.loads(hyperparams_raw)) if hyperparams_raw else None
        return FineTuneRunResponse(
            id=str(run["_id"]),
            agent_id=str(run["agent_id"]),
            user_id=str(run.get("user_id", "")),
            compute_backend=run.get("compute_backend", ""),
            status=run.get("status", "pending"),
            base_hf_model_id=run.get("base_hf_model_id", ""),
            dataset_source_type=run.get("dataset_source_type", ""),
            dataset_row_count=run.get("dataset_row_count"),
            dataset_filename=run.get("dataset_filename"),
            hyperparams=hyperparams,
            runpod_estimated_cost_usd=run.get("runpod_estimated_cost_usd"),
            runpod_actual_cost_usd=run.get("runpod_actual_cost_usd"),
            progress=_parse_progress(run.get("progress_json")),
            adapter_size_bytes=run.get("adapter_size_bytes"),
            export_to_ollama=bool(run.get("export_to_ollama", False)),
            merged_gguf_size_bytes=run.get("merged_gguf_size_bytes"),
            gguf_quantization=run.get("gguf_quantization"),
            ollama_model_tag=run.get("ollama_model_tag"),
            created_provider_id=str(run["created_provider_id"]) if run.get("created_provider_id") else None,
            created_agent_id=str(run["created_agent_id"]) if run.get("created_agent_id") else None,
            error=run.get("error"),
            created_at=run.get("created_at", datetime.now(timezone.utc)),
            started_training_at=run.get("started_training_at"),
            completed_at=run.get("completed_at"),
        )

    hyperparams = FineTuneHyperparams(**json.loads(run.hyperparams_json)) if run.hyperparams_json else None
    return FineTuneRunResponse(
        id=run.id,
        agent_id=run.agent_id,
        user_id=run.user_id,
        compute_backend=run.compute_backend,
        status=run.status,
        base_hf_model_id=run.base_hf_model_id,
        dataset_source_type=run.dataset_source_type,
        dataset_row_count=run.dataset_row_count,
        dataset_filename=run.dataset_filename,
        hyperparams=hyperparams,
        runpod_estimated_cost_usd=run.runpod_estimated_cost_usd,
        runpod_actual_cost_usd=run.runpod_actual_cost_usd,
        progress=_parse_progress(run.progress_json),
        adapter_size_bytes=run.adapter_size_bytes,
        export_to_ollama=run.export_to_ollama,
        merged_gguf_size_bytes=run.merged_gguf_size_bytes,
        gguf_quantization=run.gguf_quantization,
        ollama_model_tag=run.ollama_model_tag,
        created_provider_id=run.created_provider_id,
        created_agent_id=run.created_agent_id,
        error=run.error,
        created_at=run.created_at,
        started_training_at=run.started_training_at,
        completed_at=run.completed_at,
    )


# ─── Status ──────────────────────────────────────────────────────────────────

@router.get("/status")
async def finetune_status(current_user: TokenData = Depends(get_current_user)):
    """Whether the standalone finetune_service is reachable. The main
    backend never starts/stops it — see finetune_client.py's module
    docstring. Mirrors /inspector/status's shape."""
    return await finetune_client.ping()


# ─── Cost estimate ───────────────────────────────────────────────────────────

@router.post("/estimate-cost", response_model=FineTuneCostEstimateResponse)
async def estimate_finetune_cost(
    data: FineTuneCostEstimateRequest,
    current_user: TokenData = Depends(get_current_user),
):
    from finetune_engine import estimate_cost
    result = estimate_cost(
        base_hf_model_id=data.base_hf_model_id,
        dataset_row_count=data.dataset_row_count,
        hyperparams=data.hyperparams.model_dump(),
        compute_backend=data.compute_backend,
        export_to_ollama=data.export_to_ollama,
    )
    return FineTuneCostEstimateResponse(**result)


# ─── Trigger / list / get / delete / cancel ─────────────────────────────────

@router.post("/trigger", response_model=FineTuneRunResponse)
async def trigger_finetune(
    data: TriggerFineTuneRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from finetune_engine import run_finetune_sqlite, run_finetune_mongo

    uploaded_bytes = None
    uploaded_filename = None
    if data.dataset.type == "uploaded_file":
        if not data.dataset.file_data or not data.dataset.filename:
            raise HTTPException(status_code=400, detail="file_data and filename required for uploaded_file datasets")
        uploaded_bytes, _ = FileStorageService.decode_data_uri(data.dataset.file_data)
        uploaded_filename = data.dataset.filename

    hyperparams_json = json.dumps(data.hyperparams.model_dump())
    session_ids_json = json.dumps(data.dataset.session_ids) if data.dataset.session_ids else None

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        from bson import ObjectId
        agent = await mongo_db["agents"].find_one({"_id": ObjectId(str(data.agent_id))})
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")

        doc = {
            "agent_id": str(data.agent_id),
            "user_id": current_user.user_id,
            "compute_backend": data.compute_backend,
            "base_hf_model_id": data.base_hf_model_id,
            "dataset_source_type": data.dataset.type,
            "dataset_session_ids_json": session_ids_json,
            "dataset_filename": data.dataset.filename,
            "hyperparams_json": hyperparams_json,
            "export_to_ollama": data.export_to_ollama,
            "gguf_quantization": data.gguf_quantization,
            "auto_register_provider": data.auto_register_provider,
            "auto_register_agent": data.auto_register_agent,
        }
        run = await FineTuneRunCollection.create(mongo_db, doc)
        run_id = str(run["_id"])

        asyncio.create_task(run_finetune_mongo(run_id=run_id, uploaded_bytes=uploaded_bytes, uploaded_filename=uploaded_filename))
        return _run_to_response(run, is_mongo=True)

    # SQLite path
    agent = db.query(Agent).filter(
        Agent.id == int(data.agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    run = FineTuneRun(
        agent_id=agent.id,
        user_id=int(current_user.user_id),
        compute_backend=data.compute_backend,
        base_hf_model_id=data.base_hf_model_id,
        dataset_source_type=data.dataset.type,
        dataset_session_ids_json=session_ids_json,
        dataset_filename=data.dataset.filename,
        hyperparams_json=hyperparams_json,
        export_to_ollama=data.export_to_ollama,
        gguf_quantization=data.gguf_quantization,
        auto_register_provider=data.auto_register_provider,
        auto_register_agent=data.auto_register_agent,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(run_finetune_sqlite(run_id=run.id, uploaded_bytes=uploaded_bytes, uploaded_filename=uploaded_filename))
    return _run_to_response(run)


@router.get("/agents/{agent_id}", response_model=FineTuneRunListResponse)
async def list_agent_finetune_runs(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        runs = await FineTuneRunCollection.find_by_agent(mongo_db, agent_id)
        return FineTuneRunListResponse(runs=[_run_to_response(r, is_mongo=True) for r in runs])

    runs = db.query(FineTuneRun).filter(FineTuneRun.agent_id == int(agent_id)).order_by(FineTuneRun.created_at.desc()).all()
    return FineTuneRunListResponse(runs=[_run_to_response(r) for r in runs])


@router.get("/runs/{run_id}", response_model=FineTuneRunResponse)
async def get_finetune_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_to_response(run, is_mongo=True)

    run = db.query(FineTuneRun).filter(FineTuneRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.refresh(run)
    return _run_to_response(run)


@router.delete("/runs/{run_id}")
async def delete_finetune_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await FineTuneRunCollection.delete(mongo_db, run_id)
        if not success:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"message": "Run deleted"}

    run = db.query(FineTuneRun).filter(FineTuneRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    return {"message": "Run deleted"}


@router.post("/runs/{run_id}/cancel", response_model=FineTuneRunResponse)
async def cancel_finetune_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Requests cancellation — finetune_poller.py's next tick notices the
    'cancelled' status, best-effort cancels the backend job, and
    deregisters the poll."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.get("status") in ("completed", "failed", "cancelled"):
            raise HTTPException(status_code=400, detail="Run already finished")
        updated = await FineTuneRunCollection.update_status(mongo_db, run_id, {"status": "cancelled"})
        return _run_to_response(updated, is_mongo=True)

    run = db.query(FineTuneRun).filter(FineTuneRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Run already finished")
    run.status = "cancelled"
    db.commit()
    db.refresh(run)
    return _run_to_response(run)


# ─── Adapter download ────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/adapter")
async def download_finetune_adapter(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi import Response

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
        if not run or not run.get("adapter_storage_path"):
            raise HTTPException(status_code=404, detail="Adapter not found")
        data = await FileStorageService.read_file_gridfs(mongo_db, run["adapter_storage_path"])
        return Response(content=data, media_type="application/zip")

    run = db.query(FineTuneRun).filter(FineTuneRun.id == int(run_id)).first()
    if not run or not run.adapter_storage_path:
        raise HTTPException(status_code=404, detail="Adapter not found")
    data = FileStorageService.read_file_sqlite(run.adapter_storage_path)
    return Response(content=data, media_type="application/zip")


# ─── Retry GGUF export ───────────────────────────────────────────────────────

@router.post("/runs/{run_id}/retry-export", response_model=FineTuneRunResponse)
async def retry_gguf_export(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-runs just the GGUF export sub-pipeline on an already-trained run
    (status must already be completed/failed with an adapter present) —
    re-registers the poller job the same way finetune_engine.py does on
    initial submission."""
    from scheduler import scheduler
    from apscheduler.triggers.interval import IntervalTrigger

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await FineTuneRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.get("adapter_storage_path"):
            raise HTTPException(status_code=400, detail="No trained adapter available to export")
        updated = await FineTuneRunCollection.update_status(mongo_db, run_id, {
            "status": "merging", "export_to_ollama": True, "error": None,
        })
        from finetune_poller import poll_finetune_run_mongo
        scheduler.add_job(
            poll_finetune_run_mongo,
            trigger=IntervalTrigger(seconds=20),
            args=[run_id],
            id=f"finetune_run_{run_id}",
            replace_existing=True,
        )
        return _run_to_response(updated, is_mongo=True)

    run = db.query(FineTuneRun).filter(FineTuneRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.adapter_storage_path:
        raise HTTPException(status_code=400, detail="No trained adapter available to export")
    run.status = "merging"
    run.export_to_ollama = True
    run.error = None
    db.commit()
    db.refresh(run)

    from finetune_poller import poll_finetune_run_sqlite
    scheduler.add_job(
        poll_finetune_run_sqlite,
        trigger=IntervalTrigger(seconds=20),
        args=[run.id],
        id=f"finetune_run_{run.id}",
        replace_existing=True,
    )
    return _run_to_response(run)
