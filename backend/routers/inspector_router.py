"""Local Model Inspection router — phase 2 of model auditing.
See inspector_engine.py and models.py's InspectionRun for the full rationale.

No provider-type gating: any agent can be submitted for inspection (the
user supplies the HF model id/path themselves). Cloud-provider agents will
simply fail at the inspector service's load step with a clear error, since
their real weights are never reachable — that failure is the gate, not
something predicted in advance here."""

import json
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import InspectionRun, Agent
from schemas import (
    InspectionRunResponse,
    InspectionRunListResponse,
    InspectionSummary,
    InspectionCaptureConfig,
    TriggerInspectionRequest,
    InspectorStatusResponse,
    TriggerOptimizationRequest,
    OptimizationRunResponse,
)
from auth import get_current_user, TokenData
import inspector_client

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import InspectionRunCollection

router = APIRouter(prefix="/inspector", tags=["inspector"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_summary(summary_json: str | None) -> InspectionSummary | None:
    if not summary_json:
        return None
    try:
        return InspectionSummary(**json.loads(summary_json))
    except Exception:
        return None


def _parse_capture_config(capture_config_json: str | None) -> InspectionCaptureConfig | None:
    if not capture_config_json:
        return None
    try:
        return InspectionCaptureConfig(**json.loads(capture_config_json))
    except Exception:
        return None


def _run_to_response(run, is_mongo=False) -> InspectionRunResponse:
    if is_mongo:
        return InspectionRunResponse(
            id=str(run["_id"]),
            agent_id=str(run["agent_id"]),
            user_id=str(run.get("user_id", "")),
            status=run.get("status", "pending"),
            prompt=run.get("prompt", ""),
            hf_model_id=run.get("hf_model_id", ""),
            capture_config=_parse_capture_config(run.get("capture_config_json")),
            summary=_parse_summary(run.get("summary_json")),
            has_artifact=bool(run.get("artifact_storage_path")),
            triggered_optimization_run_id=str(run["triggered_optimization_run_id"]) if run.get("triggered_optimization_run_id") else None,
            error=run.get("error"),
            created_at=run.get("created_at", datetime.now(timezone.utc)),
            completed_at=run.get("completed_at"),
        )
    return InspectionRunResponse(
        id=run.id,
        agent_id=run.agent_id,
        user_id=run.user_id,
        status=run.status,
        prompt=run.prompt,
        hf_model_id=run.hf_model_id,
        capture_config=_parse_capture_config(run.capture_config_json),
        summary=_parse_summary(run.summary_json),
        has_artifact=bool(run.artifact_storage_path),
        triggered_optimization_run_id=run.triggered_optimization_run_id,
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


# ─── Status ──────────────────────────────────────────────────────────────────

@router.get("/status", response_model=InspectorStatusResponse)
async def inspector_status(current_user: TokenData = Depends(get_current_user)):
    """Whether the standalone inspector_service is reachable. The main
    backend never starts/stops it — see inspector_client.py's module
    docstring. Mirrors /tunnel/status's shape."""
    result = await inspector_client.ping()
    return InspectorStatusResponse(**result)


# ─── Trigger / list / get / delete ──────────────────────────────────────────

@router.post("/trigger", response_model=InspectionRunResponse)
async def trigger_inspection(
    data: TriggerInspectionRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from inspector_engine import run_inspection_sqlite, run_inspection_mongo

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent_col = mongo_db["agents"]
        from bson import ObjectId
        agent = await agent_col.find_one({"_id": ObjectId(str(data.agent_id))})
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")

        doc = {
            "agent_id": str(data.agent_id),
            "user_id": current_user.user_id,
            "prompt": data.prompt,
            "hf_model_id": data.hf_model_id,
            "capture_config_json": json.dumps(data.capture_config.model_dump()),
        }
        run = await InspectionRunCollection.create(mongo_db, doc)
        run_id = str(run["_id"])

        asyncio.create_task(run_inspection_mongo(run_id=run_id))
        return _run_to_response(run, is_mongo=True)

    # SQLite path
    agent = db.query(Agent).filter(
        Agent.id == int(data.agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    run = InspectionRun(
        agent_id=agent.id,
        user_id=int(current_user.user_id),
        prompt=data.prompt,
        hf_model_id=data.hf_model_id,
        capture_config_json=json.dumps(data.capture_config.model_dump()),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(run_inspection_sqlite(run_id=run.id))
    return _run_to_response(run)


@router.get("/agents/{agent_id}", response_model=InspectionRunListResponse)
async def list_agent_inspections(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        runs = await InspectionRunCollection.find_by_agent(mongo_db, agent_id)
        return InspectionRunListResponse(runs=[_run_to_response(r, is_mongo=True) for r in runs])

    runs = db.query(InspectionRun).filter(InspectionRun.agent_id == int(agent_id)).order_by(InspectionRun.created_at.desc()).all()
    return InspectionRunListResponse(runs=[_run_to_response(r) for r in runs])


@router.get("/runs/{run_id}", response_model=InspectionRunResponse)
async def get_inspection_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await InspectionRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_to_response(run, is_mongo=True)

    run = db.query(InspectionRun).filter(InspectionRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.refresh(run)
    return _run_to_response(run)


@router.delete("/runs/{run_id}")
async def delete_inspection_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await InspectionRunCollection.delete(mongo_db, run_id)
        if not success:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"message": "Run deleted"}

    run = db.query(InspectionRun).filter(InspectionRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    return {"message": "Run deleted"}


@router.post("/runs/{run_id}/cancel", response_model=InspectionRunResponse)
async def cancel_inspection_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request cancellation of an in-progress run — see inspector_engine.py's
    _wait_for_job, which checks this status between poll attempts and
    propagates the cancel request to the inspector service itself."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await InspectionRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.get("status") in ("completed", "failed", "cancelled"):
            raise HTTPException(status_code=400, detail="Run already finished")
        updated = await InspectionRunCollection.update_status(mongo_db, run_id, {"status": "cancelled"})
        return _run_to_response(updated, is_mongo=True)

    run = db.query(InspectionRun).filter(InspectionRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Run already finished")
    run.status = "cancelled"
    db.commit()
    db.refresh(run)
    return _run_to_response(run)


@router.post("/runs/{run_id}/trigger-optimization", response_model=OptimizationRunResponse)
async def trigger_optimization_from_inspection(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Convenience: starts a Prompt Auto-Optimizer run seeded with this
    inspection's findings. Never automatic — same explicit user-action
    gate as auditor_router.py's trigger_optimization_from_audit."""
    from routers.optimizer_router import trigger_optimization

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await InspectionRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Inspection run not found")
        agent_id = str(run["agent_id"])
    else:
        run = db.query(InspectionRun).filter(InspectionRun.id == int(run_id)).first()
        if not run:
            raise HTTPException(status_code=404, detail="Inspection run not found")
        agent_id = run.agent_id

    opt_request = TriggerOptimizationRequest(agent_id=agent_id, inspection_run_id=run_id)
    return await trigger_optimization(opt_request, current_user, db)
