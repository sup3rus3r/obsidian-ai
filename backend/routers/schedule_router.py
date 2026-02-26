"""
Schedule router — CRUD for WorkflowSchedule.
Endpoints:
  POST   /workflows/{workflow_id}/schedules
  GET    /workflows/{workflow_id}/schedules
  GET    /schedules/{schedule_id}
  PUT    /schedules/{schedule_id}
  DELETE /schedules/{schedule_id}
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from config import DATABASE_TYPE
from database import get_db
from models import Workflow, WorkflowSchedule
from schemas import (
    WorkflowScheduleCreate,
    WorkflowScheduleUpdate,
    WorkflowScheduleResponse,
    WorkflowScheduleListResponse,
)
from auth import get_current_user, TokenData
from scheduler import scheduler, build_cron_trigger, make_job_id

if DATABASE_TYPE == "mongo":
    from database_mongo import get_database
    from models_mongo import WorkflowCollection, WorkflowScheduleCollection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schedules"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_cron(expr: str) -> bool:
    try:
        from croniter import croniter
        return croniter.is_valid(expr)
    except ImportError:
        # croniter not installed — accept expression and let APScheduler validate
        return True


def _compute_next_run(cron_expr: str) -> Optional[datetime]:
    try:
        from croniter import croniter
        return croniter(cron_expr, datetime.now(timezone.utc)).get_next(datetime)
    except Exception:
        return None


def _schedule_to_response(schedule, is_mongo=False) -> WorkflowScheduleResponse:
    if is_mongo:
        return WorkflowScheduleResponse(
            id=str(schedule["_id"]),
            workflow_id=str(schedule["workflow_id"]),
            user_id=str(schedule["user_id"]),
            name=schedule["name"],
            cron_expr=schedule["cron_expr"],
            input_text=schedule.get("input_text"),
            is_active=schedule.get("is_active", True),
            last_run_at=schedule.get("last_run_at"),
            next_run_at=schedule.get("next_run_at"),
            created_at=schedule["created_at"],
        )
    return WorkflowScheduleResponse(
        id=str(schedule.id),
        workflow_id=str(schedule.workflow_id),
        user_id=str(schedule.user_id),
        name=schedule.name,
        cron_expr=schedule.cron_expr,
        input_text=schedule.input_text,
        is_active=schedule.is_active,
        last_run_at=schedule.last_run_at,
        next_run_at=schedule.next_run_at,
        created_at=schedule.created_at,
    )


def _add_apscheduler_job(schedule_id: str, cron_expr: str):
    """Register (or replace) an APScheduler job for this schedule."""
    try:
        if DATABASE_TYPE == "mongo":
            from scheduler_executor import run_scheduled_workflow_mongo as exec_fn
            args = [schedule_id]
        else:
            from scheduler_executor import run_scheduled_workflow_sqlite as exec_fn
            args = [int(schedule_id)]

        scheduler.add_job(
            exec_fn,
            trigger=build_cron_trigger(cron_expr),
            args=args,
            id=make_job_id(schedule_id),
            replace_existing=True,
        )
    except Exception as e:
        logger.warning(f"Could not register APScheduler job for schedule {schedule_id}: {e}")


def _remove_apscheduler_job(schedule_id: str):
    """Remove the APScheduler job for this schedule (if exists)."""
    try:
        job_id = make_job_id(str(schedule_id))
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    except Exception as e:
        logger.warning(f"Could not remove APScheduler job for schedule {schedule_id}: {e}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/workflows/{workflow_id}/schedules", response_model=WorkflowScheduleResponse, status_code=201)
async def create_schedule(
    workflow_id: str,
    body: WorkflowScheduleCreate,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if not _validate_cron(body.cron_expr):
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    next_run = _compute_next_run(body.cron_expr)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        workflow = await WorkflowCollection.find_by_id(mongo_db, workflow_id)
        if not workflow or workflow.get("user_id") != current_user.user_id or not workflow.get("is_active", True):
            raise HTTPException(status_code=404, detail="Workflow not found")

        doc = {
            "workflow_id": workflow_id,
            "user_id": current_user.user_id,
            "name": body.name,
            "cron_expr": body.cron_expr,
            "input_text": body.input_text,
            "is_active": body.is_active,
            "next_run_at": next_run,
        }
        created = await WorkflowScheduleCollection.create(mongo_db, doc)
        schedule_id = str(created["_id"])
        if body.is_active:
            _add_apscheduler_job(schedule_id, body.cron_expr)
        return _schedule_to_response(created, is_mongo=True)

    workflow = db.query(Workflow).filter(
        Workflow.id == int(workflow_id),
        Workflow.user_id == int(current_user.user_id),
        Workflow.is_active == True,
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    schedule = WorkflowSchedule(
        workflow_id=int(workflow_id),
        user_id=int(current_user.user_id),
        name=body.name,
        cron_expr=body.cron_expr,
        input_text=body.input_text,
        is_active=body.is_active,
        next_run_at=next_run,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    if body.is_active:
        _add_apscheduler_job(str(schedule.id), body.cron_expr)

    return _schedule_to_response(schedule)


@router.get("/workflows/{workflow_id}/schedules", response_model=WorkflowScheduleListResponse)
async def list_schedules(
    workflow_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        schedules = await WorkflowScheduleCollection.find_by_workflow(mongo_db, workflow_id, current_user.user_id)
        return WorkflowScheduleListResponse(schedules=[_schedule_to_response(s, is_mongo=True) for s in schedules])

    schedules = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.workflow_id == int(workflow_id),
        WorkflowSchedule.user_id == int(current_user.user_id),
    ).all()
    return WorkflowScheduleListResponse(schedules=[_schedule_to_response(s) for s in schedules])


@router.get("/schedules/{schedule_id}", response_model=WorkflowScheduleResponse)
async def get_schedule(
    schedule_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        schedule = await WorkflowScheduleCollection.find_by_id(mongo_db, schedule_id)
        if not schedule or schedule.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return _schedule_to_response(schedule, is_mongo=True)

    schedule = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.id == int(schedule_id),
        WorkflowSchedule.user_id == int(current_user.user_id),
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _schedule_to_response(schedule)


@router.put("/schedules/{schedule_id}", response_model=WorkflowScheduleResponse)
async def update_schedule(
    schedule_id: str,
    body: WorkflowScheduleUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)

    new_cron = updates.get("cron_expr")
    if new_cron is not None and not _validate_cron(new_cron):
        raise HTTPException(status_code=400, detail="Invalid cron expression")

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        schedule = await WorkflowScheduleCollection.find_by_id(mongo_db, schedule_id)
        if not schedule or schedule.get("user_id") != current_user.user_id:
            raise HTTPException(status_code=404, detail="Schedule not found")

        if new_cron:
            updates["next_run_at"] = _compute_next_run(new_cron)

        updated = await WorkflowScheduleCollection.update(mongo_db, schedule_id, current_user.user_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Schedule not found")

        _sync_apscheduler_job(schedule_id, updated.get("cron_expr", schedule["cron_expr"]), updated.get("is_active", schedule.get("is_active", True)))
        return _schedule_to_response(updated, is_mongo=True)

    schedule = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.id == int(schedule_id),
        WorkflowSchedule.user_id == int(current_user.user_id),
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if new_cron:
        updates["next_run_at"] = _compute_next_run(new_cron)

    for key, value in updates.items():
        setattr(schedule, key, value)
    db.commit()
    db.refresh(schedule)

    _sync_apscheduler_job(schedule_id, schedule.cron_expr, schedule.is_active)
    return _schedule_to_response(schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _remove_apscheduler_job(schedule_id)

    if DATABASE_TYPE == "mongo":
        mongo_db = get_database()
        deleted = await WorkflowScheduleCollection.delete(mongo_db, schedule_id, current_user.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return

    schedule = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.id == int(schedule_id),
        WorkflowSchedule.user_id == int(current_user.user_id),
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    db.delete(schedule)
    db.commit()


def _sync_apscheduler_job(schedule_id: str, cron_expr: str, is_active: bool):
    """Add or remove APScheduler job based on is_active flag."""
    if is_active:
        _add_apscheduler_job(schedule_id, cron_expr)
    else:
        _remove_apscheduler_job(schedule_id)
