"""Behavioral Consistency Auditor router — phase 1 of model auditing.
See auditor_engine.py and models.py's AuditRun for the full rationale."""

import json
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import AuditRun, Agent
from schemas import (
    AuditRunResponse,
    AuditRunListResponse,
    AuditProbeResult,
    TriggerAuditRequest,
    TriggerOptimizationRequest,
    OptimizationRunResponse,
)
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import AuditRunCollection

router = APIRouter(prefix="/auditor", tags=["auditor"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_results(results_json: str | None) -> list[AuditProbeResult] | None:
    if not results_json:
        return None
    try:
        raw = json.loads(results_json)
        return [AuditProbeResult(**r) for r in raw]
    except Exception:
        return None


def _run_to_response(run, is_mongo=False) -> AuditRunResponse:
    if is_mongo:
        categories_raw = run.get("probe_categories_json", "[]")
        categories = json.loads(categories_raw) if isinstance(categories_raw, str) else categories_raw
        cat_scores_raw = run.get("category_scores_json")
        cat_scores = json.loads(cat_scores_raw) if isinstance(cat_scores_raw, str) and cat_scores_raw else None
        return AuditRunResponse(
            id=str(run["_id"]),
            agent_id=str(run["agent_id"]),
            user_id=str(run.get("user_id", "")),
            status=run.get("status", "pending"),
            seed_prompt=run.get("seed_prompt", ""),
            probe_categories=categories,
            probes_per_category=run.get("probes_per_category", 5),
            judge_agent_id=str(run["judge_agent_id"]) if run.get("judge_agent_id") else None,
            results=_parse_results(run.get("results_json")),
            score=run.get("score"),
            category_scores=cat_scores,
            triggered_optimization_run_id=str(run["triggered_optimization_run_id"]) if run.get("triggered_optimization_run_id") else None,
            error=run.get("error"),
            created_at=run.get("created_at", datetime.now(timezone.utc)),
            completed_at=run.get("completed_at"),
        )
    categories = json.loads(run.probe_categories_json) if run.probe_categories_json else []
    cat_scores = json.loads(run.category_scores_json) if run.category_scores_json else None
    return AuditRunResponse(
        id=run.id,
        agent_id=run.agent_id,
        user_id=run.user_id,
        status=run.status,
        seed_prompt=run.seed_prompt,
        probe_categories=categories,
        probes_per_category=run.probes_per_category,
        judge_agent_id=run.judge_agent_id,
        results=_parse_results(run.results_json),
        score=run.score,
        category_scores=cat_scores,
        triggered_optimization_run_id=run.triggered_optimization_run_id,
        error=run.error,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


# ─── Trigger / list / get / delete ──────────────────────────────────────────

@router.post("/trigger", response_model=AuditRunResponse)
async def trigger_audit(
    data: TriggerAuditRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from auditor_engine import run_audit_sqlite, run_audit_mongo

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
            "seed_prompt": data.seed_prompt,
            "probe_categories_json": json.dumps(data.probe_categories),
            "probes_per_category": data.probes_per_category,
            "judge_agent_id": str(data.judge_agent_id) if data.judge_agent_id else None,
        }
        run = await AuditRunCollection.create(mongo_db, doc)
        run_id = str(run["_id"])

        asyncio.create_task(run_audit_mongo(
            run_id=run_id,
            agent_id=str(data.agent_id),
            seed_prompt=data.seed_prompt,
            probe_categories=data.probe_categories,
            probes_per_category=data.probes_per_category,
            judge_agent_id=str(data.judge_agent_id) if data.judge_agent_id else None,
        ))
        return _run_to_response(run, is_mongo=True)

    # SQLite path
    agent = db.query(Agent).filter(
        Agent.id == int(data.agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    run = AuditRun(
        agent_id=agent.id,
        user_id=int(current_user.user_id),
        seed_prompt=data.seed_prompt,
        probe_categories_json=json.dumps(data.probe_categories),
        probes_per_category=data.probes_per_category,
        judge_agent_id=int(data.judge_agent_id) if data.judge_agent_id else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(run_audit_sqlite(
        run_id=run.id,
        agent_id=agent.id,
        seed_prompt=data.seed_prompt,
        probe_categories=data.probe_categories,
        probes_per_category=data.probes_per_category,
        judge_agent_id=int(data.judge_agent_id) if data.judge_agent_id else None,
    ))
    return _run_to_response(run)


@router.get("/agents/{agent_id}", response_model=AuditRunListResponse)
async def list_agent_audits(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        runs = await AuditRunCollection.find_by_agent(mongo_db, agent_id)
        return AuditRunListResponse(runs=[_run_to_response(r, is_mongo=True) for r in runs])

    runs = db.query(AuditRun).filter(AuditRun.agent_id == int(agent_id)).order_by(AuditRun.created_at.desc()).all()
    return AuditRunListResponse(runs=[_run_to_response(r) for r in runs])


@router.get("/runs/{run_id}", response_model=AuditRunResponse)
async def get_audit_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await AuditRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_to_response(run, is_mongo=True)

    run = db.query(AuditRun).filter(AuditRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.refresh(run)
    return _run_to_response(run)


@router.delete("/runs/{run_id}")
async def delete_audit_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await AuditRunCollection.delete(mongo_db, run_id)
        if not success:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"message": "Run deleted"}

    run = db.query(AuditRun).filter(AuditRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    return {"message": "Run deleted"}


@router.post("/runs/{run_id}/cancel", response_model=AuditRunResponse)
async def cancel_audit_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Request cancellation of an in-progress run. The background task
    (auditor_engine.py) checks this status between stages and in-flight LLM
    calls for the current batch are not aborted mid-flight, but no further
    batches start and whatever results already landed are kept and scored."""
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await AuditRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.get("status") in ("completed", "failed", "cancelled"):
            raise HTTPException(status_code=400, detail="Run already finished")
        updated = await AuditRunCollection.update_status(mongo_db, run_id, {"status": "cancelled"})
        return _run_to_response(updated, is_mongo=True)

    run = db.query(AuditRun).filter(AuditRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in ("completed", "failed", "cancelled"):
        raise HTTPException(status_code=400, detail="Run already finished")
    run.status = "cancelled"
    db.commit()
    db.refresh(run)
    return _run_to_response(run)


@router.post("/runs/{run_id}/trigger-optimization", response_model=OptimizationRunResponse)
async def trigger_optimization_from_audit(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Convenience: starts a Prompt Auto-Optimizer run seeded with this
    audit's findings. Never called automatically — always an explicit
    user action, matching the optimizer's existing review-gated design
    (no auto-apply anywhere in this codebase)."""
    from routers.optimizer_router import trigger_optimization

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await AuditRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Audit run not found")
        agent_id = str(run["agent_id"])
    else:
        run = db.query(AuditRun).filter(AuditRun.id == int(run_id)).first()
        if not run:
            raise HTTPException(status_code=404, detail="Audit run not found")
        agent_id = run.agent_id

    opt_request = TriggerOptimizationRequest(agent_id=agent_id, audit_run_id=run_id)
    return await trigger_optimization(opt_request, current_user, db)
