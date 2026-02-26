"""Global APScheduler instance + configuration helpers."""
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.triggers.cron import CronTrigger

# Single global scheduler instance
scheduler = AsyncIOScheduler(
    executors={"default": AsyncIOExecutor()},
    job_defaults={
        "coalesce": True,         # collapse missed runs into one
        "misfire_grace_time": None,  # skip missed runs entirely
        "max_instances": 1,
    },
)


def configure_scheduler():
    """Attach the appropriate jobstore based on DATABASE_TYPE env var."""
    DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent_control_plane.db")

    if DATABASE_TYPE == "mongo":
        from apscheduler.jobstores.mongodb import MongoDBJobStore
        MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "aios")
        jobstore = MongoDBJobStore(host=MONGO_URL, database=f"{MONGO_DB_NAME}_jobs")
    else:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        jobstore = SQLAlchemyJobStore(url=DATABASE_URL)

    scheduler.configure(jobstores={"default": jobstore})


def build_cron_trigger(cron_expr: str) -> CronTrigger:
    """Parse a 5-field cron expression into an APScheduler CronTrigger."""
    fields = cron_expr.split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5-field cron expression, got: {cron_expr!r}")
    minute, hour, day, month, day_of_week = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


def make_job_id(schedule_id: str) -> str:
    """Stable job ID for a given schedule."""
    return f"workflow_schedule_{schedule_id}"
