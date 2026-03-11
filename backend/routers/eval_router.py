"""Eval harness router: CRUD for suites and run management."""

import json
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from config import DATABASE_TYPE
from database import get_db
from models import EvalSuite, EvalRun, Agent
from schemas import (
    EvalSuiteCreate,
    EvalSuiteUpdate,
    EvalSuiteResponse,
    EvalSuiteListResponse,
    EvalRunResponse,
    EvalRunListResponse,
    EvalCaseResult,
    EvalTestCase,
    RunEvalRequest,
)
from auth import get_current_user, TokenData

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import EvalSuiteCollection, EvalRunCollection

router = APIRouter(prefix="/evals", tags=["evals"])


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_results(results_json: str | None) -> list[EvalCaseResult] | None:
    if not results_json:
        return None
    try:
        raw = json.loads(results_json)
        return [EvalCaseResult(**r) for r in raw]
    except Exception:
        return None


def _suite_to_response(suite, is_mongo=False) -> EvalSuiteResponse:
    if is_mongo:
        raw_cases = suite.get("test_cases_json", "[]")
        cases = json.loads(raw_cases) if isinstance(raw_cases, str) else raw_cases
        return EvalSuiteResponse(
            id=str(suite["_id"]),
            user_id=str(suite.get("user_id", "")),
            agent_id=str(suite["agent_id"]) if suite.get("agent_id") else None,
            judge_agent_id=str(suite["judge_agent_id"]) if suite.get("judge_agent_id") else None,
            name=suite["name"],
            description=suite.get("description"),
            test_cases=[EvalTestCase(**c) for c in cases],
            created_at=suite.get("created_at", datetime.now(timezone.utc)),
            updated_at=suite.get("updated_at"),
        )
    cases = json.loads(suite.test_cases_json) if suite.test_cases_json else []
    return EvalSuiteResponse(
        id=suite.id,
        user_id=suite.user_id,
        agent_id=suite.agent_id,
        judge_agent_id=suite.judge_agent_id,
        name=suite.name,
        description=suite.description,
        test_cases=[EvalTestCase(**c) for c in cases],
        created_at=suite.created_at,
        updated_at=suite.updated_at,
    )


def _run_to_response(run, is_mongo=False) -> EvalRunResponse:
    if is_mongo:
        results_raw = run.get("results_json")
        return EvalRunResponse(
            id=str(run["_id"]),
            suite_id=str(run.get("suite_id", "")),
            agent_id=str(run["agent_id"]) if run.get("agent_id") else None,
            version_id=str(run["version_id"]) if run.get("version_id") else None,
            status=run.get("status", "pending"),
            results=_parse_results(results_raw),
            score=run.get("score"),
            total_cases=run.get("total_cases", 0),
            passed_cases=run.get("passed_cases", 0),
            created_at=run.get("created_at", datetime.now(timezone.utc)),
            completed_at=run.get("completed_at"),
        )
    return EvalRunResponse(
        id=run.id,
        suite_id=run.suite_id,
        agent_id=run.agent_id,
        version_id=run.version_id,
        status=run.status,
        results=_parse_results(run.results_json),
        score=run.score,
        total_cases=run.total_cases,
        passed_cases=run.passed_cases,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


# ─── Suite CRUD ──────────────────────────────────────────────────────────────

@router.get("/suites", response_model=EvalSuiteListResponse)
async def list_suites(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        suites = await EvalSuiteCollection.find_by_user(mongo_db, current_user.user_id)
        return EvalSuiteListResponse(suites=[_suite_to_response(s, is_mongo=True) for s in suites])

    suites = db.query(EvalSuite).filter(EvalSuite.user_id == int(current_user.user_id)).order_by(EvalSuite.created_at.desc()).all()
    return EvalSuiteListResponse(suites=[_suite_to_response(s) for s in suites])


@router.post("/suites", response_model=EvalSuiteResponse)
async def create_suite(
    data: EvalSuiteCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cases_json = json.dumps([c.model_dump() for c in data.test_cases])

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        doc = {
            "user_id": current_user.user_id,
            "agent_id": str(data.agent_id) if data.agent_id is not None else None,
            "judge_agent_id": str(data.judge_agent_id) if data.judge_agent_id is not None else None,
            "name": data.name,
            "description": data.description,
            "test_cases_json": cases_json,
        }
        created = await EvalSuiteCollection.create(mongo_db, doc)
        return _suite_to_response(created, is_mongo=True)

    agent_id = int(data.agent_id) if data.agent_id is not None else None
    judge_agent_id = int(data.judge_agent_id) if data.judge_agent_id is not None else None
    suite = EvalSuite(
        user_id=int(current_user.user_id),
        agent_id=agent_id,
        judge_agent_id=judge_agent_id,
        name=data.name,
        description=data.description,
        test_cases_json=cases_json,
    )
    db.add(suite)
    db.commit()
    db.refresh(suite)
    return _suite_to_response(suite)


@router.get("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def get_suite(
    suite_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        suite = await EvalSuiteCollection.find_by_id(mongo_db, suite_id)
        if not suite or suite.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Suite not found")
        return _suite_to_response(suite, is_mongo=True)

    suite = db.query(EvalSuite).filter(
        EvalSuite.id == int(suite_id),
        EvalSuite.user_id == int(current_user.user_id),
    ).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    return _suite_to_response(suite)


@router.put("/suites/{suite_id}", response_model=EvalSuiteResponse)
async def update_suite(
    suite_id: str,
    data: EvalSuiteUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates: dict = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.description is not None:
        updates["description"] = data.description
    if data.agent_id is not None:
        updates["agent_id"] = data.agent_id  # kept as str; cast per backend below
    if data.judge_agent_id is not None:
        updates["judge_agent_id"] = data.judge_agent_id
    if data.test_cases is not None:
        updates["test_cases_json"] = json.dumps([c.model_dump() for c in data.test_cases])

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        if "agent_id" in updates:
            updates["agent_id"] = str(updates["agent_id"]) if updates["agent_id"] else None
        if "judge_agent_id" in updates:
            updates["judge_agent_id"] = str(updates["judge_agent_id"]) if updates["judge_agent_id"] else None
        updated = await EvalSuiteCollection.update(mongo_db, suite_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Suite not found")
        return _suite_to_response(updated, is_mongo=True)

    suite = db.query(EvalSuite).filter(
        EvalSuite.id == int(suite_id),
        EvalSuite.user_id == int(current_user.user_id),
    ).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    if "agent_id" in updates and updates["agent_id"] is not None:
        updates["agent_id"] = int(updates["agent_id"])
    if "judge_agent_id" in updates and updates["judge_agent_id"] is not None:
        updates["judge_agent_id"] = int(updates["judge_agent_id"])
    for key, val in updates.items():
        setattr(suite, key, val)
    db.commit()
    db.refresh(suite)
    return _suite_to_response(suite)


@router.delete("/suites/{suite_id}")
async def delete_suite(
    suite_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await EvalSuiteCollection.delete(mongo_db, suite_id, current_user.user_id)
        if not success:
            raise HTTPException(status_code=404, detail="Suite not found")
        return {"message": "Suite deleted"}

    suite = db.query(EvalSuite).filter(
        EvalSuite.id == int(suite_id),
        EvalSuite.user_id == int(current_user.user_id),
    ).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")
    db.delete(suite)
    db.commit()
    return {"message": "Suite deleted"}


# ─── Run management ──────────────────────────────────────────────────────────

@router.post("/suites/{suite_id}/run", response_model=EvalRunResponse)
async def trigger_run(
    suite_id: str,
    data: RunEvalRequest,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from eval_engine import run_eval_suite_sqlite, run_eval_suite_mongo

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        suite = await EvalSuiteCollection.find_by_id(mongo_db, suite_id)
        if not suite or suite.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Suite not found")

        cases_raw = suite.get("test_cases_json", "[]")
        cases = json.loads(cases_raw) if isinstance(cases_raw, str) else cases_raw

        doc = {
            "suite_id": suite_id,
            "agent_id": str(data.agent_id),
            "version_id": str(data.version_id) if data.version_id else None,
            "agent_config_snapshot": None,
            "total_cases": len(cases),
        }
        run = await EvalRunCollection.create(mongo_db, doc)
        run_id = str(run["_id"])

        asyncio.create_task(run_eval_suite_mongo(
            suite_id=suite_id,
            agent_id=str(data.agent_id),
            run_id=run_id,
            override_system_prompt=data.override_system_prompt,
            version_id=str(data.version_id) if data.version_id else None,
        ))
        return _run_to_response(run, is_mongo=True)

    # SQLite path
    suite = db.query(EvalSuite).filter(
        EvalSuite.id == int(suite_id),
        EvalSuite.user_id == int(current_user.user_id),
    ).first()
    if not suite:
        raise HTTPException(status_code=404, detail="Suite not found")

    cases = json.loads(suite.test_cases_json) if suite.test_cases_json else []
    run = EvalRun(
        suite_id=suite.id,
        agent_id=int(data.agent_id),
        version_id=int(data.version_id) if data.version_id else None,
        total_cases=len(cases),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(run_eval_suite_sqlite(
        suite_id=suite.id,
        agent_id=int(data.agent_id),
        run_id=run.id,
        db=db,
        override_system_prompt=data.override_system_prompt,
        version_id=int(data.version_id) if data.version_id else None,
    ))
    return _run_to_response(run)


@router.get("/runs/{run_id}", response_model=EvalRunResponse)
async def get_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        run = await EvalRunCollection.find_by_id(mongo_db, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return _run_to_response(run, is_mongo=True)

    run = db.query(EvalRun).filter(EvalRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # Refresh for latest status (background task may have updated it)
    db.refresh(run)
    return _run_to_response(run)


@router.get("/suites/{suite_id}/runs", response_model=EvalRunListResponse)
async def list_suite_runs(
    suite_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        runs = await EvalRunCollection.find_by_suite(mongo_db, suite_id)
        return EvalRunListResponse(runs=[_run_to_response(r, is_mongo=True) for r in runs])

    runs = db.query(EvalRun).filter(EvalRun.suite_id == int(suite_id)).order_by(EvalRun.created_at.desc()).all()
    return EvalRunListResponse(runs=[_run_to_response(r) for r in runs])


@router.get("/agents/{agent_id}/runs", response_model=EvalRunListResponse)
async def list_agent_runs(
    agent_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        runs = await EvalRunCollection.find_by_agent(mongo_db, agent_id)
        return EvalRunListResponse(runs=[_run_to_response(r, is_mongo=True) for r in runs])

    runs = db.query(EvalRun).filter(EvalRun.agent_id == int(agent_id)).order_by(EvalRun.created_at.desc()).all()
    return EvalRunListResponse(runs=[_run_to_response(r) for r in runs])


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        success = await EvalRunCollection.delete(mongo_db, run_id)
        if not success:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"message": "Run deleted"}

    run = db.query(EvalRun).filter(EvalRun.id == int(run_id)).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    db.delete(run)
    db.commit()
    return {"message": "Run deleted"}
