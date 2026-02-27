import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
import uvicorn

from dotenv import load_dotenv
load_dotenv()

from config import DATABASE_TYPE
from database import engine, Base
from rate_limiter import limiter, rate_limit_exceeded_handler

from routers.auth_router import router as auth_router
from routers.user_router import router as user_router
from routers.providers_router import router as providers_router
from routers.agents_router import router as agents_router
from routers.teams_router import router as teams_router
from routers.workflows_router import router as workflows_router
from routers.sessions_router import router as sessions_router
from routers.chat_router import router as chat_router
from routers.dashboard_router import router as dashboard_router
from routers.tools_router import router as tools_router
from routers.mcp_servers_router import router as mcp_servers_router
from routers.admin_router import router as admin_router
from routers.workflow_runs_router import router as workflow_runs_router
from routers.secrets_router import router as secrets_router
from routers.files_router import router as files_router
from routers.knowledge_router import router as knowledge_router
from routers.schedule_router import router as schedule_router
from routers.memory_router import router as memory_router
from routers.traces_router import router as traces_router

if DATABASE_TYPE == "mongo":
    from database_mongo import connect_to_mongo, close_mongo_connection, get_database
    from models_mongo import (
        UserCollection, APIClientCollection, LLMProviderCollection,
        AgentCollection, TeamCollection, WorkflowCollection, WorkflowRunCollection,
        SessionCollection, MessageCollection, ToolDefinitionCollection, MCPServerCollection,
        UserSecretCollection, FileAttachmentCollection,
        KnowledgeBaseCollection, KBDocumentCollection,
        WorkflowScheduleCollection, HITLApprovalCollection,
        AgentMemoryCollection,
        TraceSpanCollection,
        ToolProposalCollection,
    )


def _run_sqlite_migrations(engine):
    """Add columns/tables that create_all won't add to existing tables."""
    import sqlalchemy
    with engine.connect() as conn:
        # Add mcp_servers_json to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN mcp_servers_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add permissions_json to users if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE users ADD COLUMN permissions_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add session_id to workflow_runs if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE workflow_runs ADD COLUMN session_id INTEGER REFERENCES sessions(id)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add totp_secret to users if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE users ADD COLUMN totp_secret TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add totp_enabled to users if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create user_secrets table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS user_secrets (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add attachments_json to messages if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE messages ADD COLUMN attachments_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add rating to messages if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE messages ADD COLUMN rating TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add secret_id to llm_providers if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE llm_providers ADD COLUMN secret_id INTEGER"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create file_attachments table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS file_attachments (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    message_id INTEGER REFERENCES messages(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER,
                    storage_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create knowledge_bases table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL,
                    description TEXT,
                    is_shared BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create kb_documents table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id INTEGER PRIMARY KEY,
                    kb_id INTEGER NOT NULL REFERENCES knowledge_bases(id),
                    doc_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content_text TEXT,
                    file_id TEXT,
                    filename TEXT,
                    media_type TEXT,
                    indexed BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add knowledge_base_ids_json to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN knowledge_base_ids_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add total_input_tokens to sessions if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE sessions ADD COLUMN total_input_tokens INTEGER DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add total_output_tokens to sessions if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE sessions ADD COLUMN total_output_tokens INTEGER DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create workflow_schedules table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS workflow_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id INTEGER NOT NULL REFERENCES workflows(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL,
                    cron_expr TEXT NOT NULL,
                    input_text TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    last_run_at DATETIME,
                    next_run_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add requires_confirmation to tool_definitions if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE tool_definitions ADD COLUMN requires_confirmation BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add hitl_confirmation_tools_json to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN hitl_confirmation_tools_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create hitl_approvals table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS hitl_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    tool_call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_arguments_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add memory_processed to sessions if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE sessions ADD COLUMN memory_processed BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create agent_memories table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS agent_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'context',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    session_id INTEGER REFERENCES sessions(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create trace_spans table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS trace_spans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER REFERENCES sessions(id),
                    workflow_run_id INTEGER REFERENCES workflow_runs(id),
                    message_id INTEGER REFERENCES messages(id),
                    span_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'success',
                    input_data TEXT,
                    output_data TEXT,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    round_number INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add allow_tool_creation to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN allow_tool_creation BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create tool_proposals table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS tool_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    tool_call_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    handler_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    handler_config_json TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_tool_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add model_id to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN model_id TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Data migration: copy provider.model_id → agent.model_id for agents that don't have one yet
        try:
            conn.execute(sqlalchemy.text("""
                UPDATE agents
                SET model_id = (
                    SELECT llm_providers.model_id
                    FROM llm_providers
                    WHERE llm_providers.id = agents.provider_id
                    AND llm_providers.model_id IS NOT NULL
                )
                WHERE agents.model_id IS NULL
                AND agents.provider_id IS NOT NULL
            """))
            conn.commit()
        except Exception:
            conn.rollback()


async def _load_active_schedules():
    """Re-register APScheduler jobs for all active schedules on startup."""
    from scheduler import scheduler as _sched, build_cron_trigger, make_job_id
    try:
        if DATABASE_TYPE == "mongo":
            from scheduler_executor import run_scheduled_workflow_mongo as exec_fn
            mongo_db = get_database()
            schedules = await WorkflowScheduleCollection.find_all_active(mongo_db)
            for s in schedules:
                sid = str(s["_id"])
                try:
                    _sched.add_job(
                        exec_fn,
                        trigger=build_cron_trigger(s["cron_expr"]),
                        args=[sid],
                        id=make_job_id(sid),
                        replace_existing=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Could not restore schedule {sid}: {e}")
        else:
            from scheduler_executor import run_scheduled_workflow_sqlite as exec_fn
            from models import WorkflowSchedule
            db = get_db_sync()
            try:
                schedules = db.query(WorkflowSchedule).filter(WorkflowSchedule.is_active == True).all()
                for s in schedules:
                    try:
                        _sched.add_job(
                            exec_fn,
                            trigger=build_cron_trigger(s.cron_expr),
                            args=[s.id],
                            id=make_job_id(str(s.id)),
                            replace_existing=True,
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Could not restore schedule {s.id}: {e}")
            finally:
                db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to load active schedules: {e}")


def get_db_sync():
    """Return a raw SQLAlchemy session (not a FastAPI dependency)."""
    from database import SessionLocal
    return SessionLocal()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_TYPE == "sqlite":
        Base.metadata.create_all(bind=engine)
        _run_sqlite_migrations(engine)
        import sqlalchemy
        with engine.connect() as conn:
            # Auto-deny any HITL approvals left pending from a previous server run
            conn.execute(sqlalchemy.text(
                "UPDATE hitl_approvals SET status='denied', resolved_at=CURRENT_TIMESTAMP WHERE status='pending'"
            ))
            # Auto-reject any tool proposals left pending from a previous server run
            conn.execute(sqlalchemy.text(
                "UPDATE tool_proposals SET status='rejected', resolved_at=CURRENT_TIMESTAMP WHERE status='pending'"
            ))
            conn.commit()
    elif DATABASE_TYPE == "mongo":
        await connect_to_mongo()
        db = get_database()
        await UserCollection.create_indexes(db)
        await APIClientCollection.create_indexes(db)
        await LLMProviderCollection.create_indexes(db)
        await AgentCollection.create_indexes(db)
        await TeamCollection.create_indexes(db)
        await WorkflowCollection.create_indexes(db)
        await WorkflowRunCollection.create_indexes(db)
        await SessionCollection.create_indexes(db)
        await MessageCollection.create_indexes(db)
        await ToolDefinitionCollection.create_indexes(db)
        await MCPServerCollection.create_indexes(db)
        await UserSecretCollection.create_indexes(db)
        await FileAttachmentCollection.create_indexes(db)
        await KnowledgeBaseCollection.create_indexes(db)
        await KBDocumentCollection.create_indexes(db)
        await WorkflowScheduleCollection.create_indexes(db)
        await HITLApprovalCollection.create_indexes(db)
        await AgentMemoryCollection.create_indexes(db)
        await TraceSpanCollection.create_indexes(db)
        await ToolProposalCollection.create_indexes(db)
        # Auto-deny any HITL approvals left pending from a previous server run
        await HITLApprovalCollection.deny_all_pending(db)
        # Auto-reject any tool proposals left pending from a previous server run
        await ToolProposalCollection.reject_all_pending(db)
        # Data migration: copy provider.model_id → agent.model_id where agent has no model_id
        from bson import ObjectId as _ObjId
        async for agent in db.agents.find({"model_id": {"$exists": False}}):
            if agent.get("provider_id"):
                try:
                    provider = await db.llm_providers.find_one({"_id": _ObjId(agent["provider_id"])})
                    if provider and provider.get("model_id"):
                        await db.agents.update_one(
                            {"_id": agent["_id"]},
                            {"$set": {"model_id": provider["model_id"]}}
                        )
                except Exception:
                    pass

    # Start APScheduler
    from scheduler import scheduler as _scheduler, configure_scheduler
    configure_scheduler()
    await _load_active_schedules()
    _scheduler.start()

    yield

    # Shutdown APScheduler
    _scheduler.shutdown(wait=False)
    if DATABASE_TYPE == "mongo":
        await close_mongo_connection()


app = FastAPI(title="Obsidian AI", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(providers_router)
app.include_router(agents_router)
app.include_router(teams_router)
app.include_router(workflows_router)
app.include_router(sessions_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(tools_router)
app.include_router(mcp_servers_router)
app.include_router(admin_router)
app.include_router(workflow_runs_router)
app.include_router(secrets_router)
app.include_router(files_router)
app.include_router(knowledge_router)
app.include_router(schedule_router)
app.include_router(memory_router)
app.include_router(traces_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
