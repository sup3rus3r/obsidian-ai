"""Prompt Auto-Optimizer REST endpoints.

Routes:
  POST   /optimizer/trigger           — start a new optimization run
  GET    /optimizer/agents/{agent_id} — list runs for an agent
  GET    /optimizer/runs/{run_id}     — get a single run (poll for status)
  POST   /optimizer/runs/{run_id}/accept  — accept proposal (applies to agent)
  POST   /optimizer/runs/{run_id}/reject  — reject proposal
  DELETE /optimizer/runs/{run_id}     — delete a run record
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_user, TokenData
from config import DATABASE_TYPE
from database import get_db
from models import Agent, OptimizationRun, AgentVersion
from schemas import (
    OptimizationRunResponse,
    OptimizationRunListResponse,
    FailurePattern,
    TriggerOptimizationRequest,
    RejectOptimizationRequest,
)
from optimizer import start_optimization_sqlite, start_optimization_mongo

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import (
        AgentCollection,
        OptimizationRunCollection,
        AgentVersionCollection,
    )

router = APIRouter(prefix="/optimizer", tags=["optimizer"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _run_to_response(run) -> OptimizationRunResponse:
    patterns = None
    if run.failure_patterns:
        raw = json.loads(run.failure_patterns) if isinstance(run.failure_patterns, str) else run.failure_patterns
        patterns = [FailurePattern(**p) for p in raw] if raw else None

    return OptimizationRunResponse(
        id=run.id,
        agent_id=run.agent_id,
        user_id=run.user_id,
        status=run.status,
        trace_count=run.trace_count or 0,
        failure_patterns=patterns,
        current_prompt=run.current_prompt,
        proposed_prompt=run.proposed_prompt,
        rationale=run.rationale,
        eval_suite_id=run.eval_suite_id,
        eval_run_id=run.eval_run_id,
        baseline_score=run.baseline_score,
        proposed_score=run.proposed_score,
        accepted_version_id=run.accepted_version_id,
        rejected_reason=run.rejected_reason,
        error_message=run.error_message,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _doc_to_response(doc: dict) -> OptimizationRunResponse:
    patterns = None
    fp_raw = doc.get("failure_patterns")
    if fp_raw:
        if isinstance(fp_raw, str):
            fp_raw = json.loads(fp_raw)
        patterns = [FailurePattern(**p) for p in fp_raw] if fp_raw else None

    return OptimizationRunResponse(
        id=str(doc["_id"]),
        agent_id=doc["agent_id"],
        user_id=doc["user_id"],
        status=doc.get("status", "pending"),
        trace_count=doc.get("trace_count", 0),
        failure_patterns=patterns,
        current_prompt=doc.get("current_prompt"),
        proposed_prompt=doc.get("proposed_prompt"),
        rationale=doc.get("rationale"),
        eval_suite_id=doc.get("eval_suite_id"),
        eval_run_id=doc.get("eval_run_id"),
        baseline_score=doc.get("baseline_score"),
        proposed_score=doc.get("proposed_score"),
        accepted_version_id=doc.get("accepted_version_id"),
        rejected_reason=doc.get("rejected_reason"),
        error_message=doc.get("error_message"),
        created_at=doc.get("created_at", datetime.now(timezone.utc)),
        completed_at=doc.get("completed_at"),
    )


# ─── POST /optimizer/trigger ─────────────────────────────────────────────────

@router.post("/trigger", response_model=OptimizationRunResponse)
async def trigger_optimization(
    body: TriggerOptimizationRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, str(body.agent_id))
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")

        doc = await OptimizationRunCollection.create(mongo_db, {
            "agent_id": str(body.agent_id),
            "user_id": current_user.user_id,
            "eval_suite_id": str(body.eval_suite_id) if body.eval_suite_id else None,
            "status": "pending",
            "trace_count": 0,
        })
        run_id = str(doc["_id"])

        start_optimization_mongo(
            run_id=run_id,
            agent_id=str(body.agent_id),
            user_id=current_user.user_id,
            eval_suite_id=str(body.eval_suite_id) if body.eval_suite_id else None,
            min_traces=body.min_traces,
            max_traces=body.max_traces,
        )
        return _doc_to_response(doc)

    # SQLite
    agent = db.query(Agent).filter(
        Agent.id == int(body.agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    run = OptimizationRun(
        agent_id=int(body.agent_id),
        user_id=int(current_user.user_id),
        eval_suite_id=int(body.eval_suite_id) if body.eval_suite_id else None,
        status="pending",
        trace_count=0,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    start_optimization_sqlite(
        run_id=run.id,
        agent_id=int(body.agent_id),
        user_id=int(current_user.user_id),
        eval_suite_id=int(body.eval_suite_id) if body.eval_suite_id else None,
        min_traces=body.min_traces,
        max_traces=body.max_traces,
    )
    return _run_to_response(run)


# ─── GET /optimizer/agents/{agent_id} ────────────────────────────────────────

@router.get("/agents/{agent_id}", response_model=OptimizationRunListResponse)
async def list_optimization_runs(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        agent = await AgentCollection.find_by_id(mongo_db, agent_id)
        if not agent or agent.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Agent not found")
        docs = await OptimizationRunCollection.find_by_agent(mongo_db, agent_id)
        return OptimizationRunListResponse(runs=[_doc_to_response(d) for d in docs])

    agent = db.query(Agent).filter(
        Agent.id == int(agent_id),
        Agent.user_id == int(current_user.user_id),
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    runs = db.query(OptimizationRun).filter(
        OptimizationRun.agent_id == int(agent_id),
        OptimizationRun.user_id == int(current_user.user_id),
    ).order_by(OptimizationRun.created_at.desc()).all()
    return OptimizationRunListResponse(runs=[_run_to_response(r) for r in runs])


# ─── GET /optimizer/runs/{run_id} ────────────────────────────────────────────

@router.get("/runs/{run_id}", response_model=OptimizationRunResponse)
async def get_optimization_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = await OptimizationRunCollection.find_by_id(mongo_db, run_id)
        if not doc or doc.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Run not found")
        return _doc_to_response(doc)

    run = db.query(OptimizationRun).filter(
        OptimizationRun.id == int(run_id),
        OptimizationRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_response(run)


# ─── POST /optimizer/runs/{run_id}/accept ────────────────────────────────────

@router.post("/runs/{run_id}/accept", response_model=OptimizationRunResponse)
async def accept_optimization(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply the proposed prompt to the agent and snapshot the previous state."""
    from routers.agents_router import _snapshot_agent_sqlite, _snapshot_agent_mongo

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = await OptimizationRunCollection.find_by_id(mongo_db, run_id)
        if not doc or doc.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Run not found")
        if doc.get("status") != "awaiting_review":
            raise HTTPException(status_code=400, detail="Run is not awaiting review")

        agent = await AgentCollection.find_by_id(mongo_db, doc["agent_id"])
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Snapshot current state
        version = await _snapshot_agent_mongo(
            mongo_db, agent, "Optimizer accepted"
        )
        version_id = str(version["_id"])

        # Apply proposed prompt
        await AgentCollection.update(
            mongo_db, doc["agent_id"], current_user.user_id,
            {"system_prompt": doc["proposed_prompt"]}
        )

        updates = {
            "status": "accepted",
            "accepted_version_id": version_id,
            "completed_at": datetime.now(timezone.utc),
        }
        updated = await OptimizationRunCollection.update_status(mongo_db, run_id, updates)
        return _doc_to_response(updated)

    # SQLite
    run = db.query(OptimizationRun).filter(
        OptimizationRun.id == int(run_id),
        OptimizationRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "awaiting_review":
        raise HTTPException(status_code=400, detail="Run is not awaiting review")

    agent = db.query(Agent).filter(Agent.id == run.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Snapshot current state (before applying)
    version = _snapshot_agent_sqlite(db, agent, "Optimizer accepted")
    db.flush()  # get version.id without full commit yet

    # Apply proposed prompt
    agent.system_prompt = run.proposed_prompt

    run.status = "accepted"
    run.accepted_version_id = version.id
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _run_to_response(run)


# ─── POST /optimizer/runs/{run_id}/reject ────────────────────────────────────

@router.post("/runs/{run_id}/reject", response_model=OptimizationRunResponse)
async def reject_optimization(
    run_id: str,
    body: RejectOptimizationRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = await OptimizationRunCollection.find_by_id(mongo_db, run_id)
        if not doc or doc.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Run not found")
        if doc.get("status") != "awaiting_review":
            raise HTTPException(status_code=400, detail="Run is not awaiting review")

        updates = {
            "status": "rejected",
            "rejected_reason": body.reason,
            "completed_at": datetime.now(timezone.utc),
        }
        updated = await OptimizationRunCollection.update_status(mongo_db, run_id, updates)
        return _doc_to_response(updated)

    run = db.query(OptimizationRun).filter(
        OptimizationRun.id == int(run_id),
        OptimizationRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "awaiting_review":
        raise HTTPException(status_code=400, detail="Run is not awaiting review")

    run.status = "rejected"
    run.rejected_reason = body.reason
    run.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return _run_to_response(run)


# ─── DELETE /optimizer/runs/{run_id} ─────────────────────────────────────────

@router.delete("/runs/{run_id}")
async def delete_optimization_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = await OptimizationRunCollection.find_by_id(mongo_db, run_id)
        if not doc or doc.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Run not found")
        await OptimizationRunCollection.delete(mongo_db, run_id)
        return {"message": "Run deleted"}

    run = db.query(OptimizationRun).filter(
        OptimizationRun.id == int(run_id),
        OptimizationRun.user_id == int(current_user.user_id),
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    return {"message": "Run deleted"}
