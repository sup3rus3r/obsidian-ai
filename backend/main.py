import asyncio
import json
import sys
import logging
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
import uvicorn

from dotenv import load_dotenv
load_dotenv()

from config import DATABASE_TYPE
from database import engine, Base
from rate_limiter import limiter, rate_limit_exceeded_handler
from auth import get_current_user, TokenData

from routers.auth_router import router as auth_router
from routers.user_router import router as user_router
from routers.providers_router import router as providers_router
from routers.agents_router import router as agents_router
from routers.agent_api_router import router as agent_api_router
from routers.public_api_router import router as public_api_router
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
from routers.versions_router import router as versions_router
from routers.eval_router import router as eval_router
from routers.auditor_router import router as auditor_router
from routers.inspector_router import router as inspector_router
from routers.finetune_router import router as finetune_router
from routers.optimizer_router import router as optimizer_router
from routers.settings_router import router as settings_router
from routers.sandbox_router import router as sandbox_router
from routers.analytics_router import router as analytics_router
from routers.whatsapp_router import router as whatsapp_router
from routers.prompt_vault_router import router as prompt_vault_router
from routers.vault_router import router as vault_router
from routers.skills_router import router as skills_router

if DATABASE_TYPE == "mongo":
    from database_mongo import connect_to_mongo, close_mongo_connection, get_database
    from models_mongo import (
        UserCollection, APIClientCollection, LLMProviderCollection,
        AgentCollection, TeamCollection, WorkflowCollection, WorkflowRunCollection,
        SessionCollection, MessageCollection, AgentThreadMessageCollection, TeamMemberCollection, ToolDefinitionCollection, SkillCollection, MCPServerCollection,
        UserSecretCollection, FileAttachmentCollection,
        KnowledgeBaseCollection, KBDocumentCollection,
        WorkflowScheduleCollection, HITLApprovalCollection,
        AgentMemoryCollection,
        TraceSpanCollection,
        ToolProposalCollection,
        WhatsAppChannelCollection,
        WAContactSessionCollection,
        AsyncJobCollection,
        WorkflowApprovalCollection,
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

        # Add secret_type to user_secrets if missing (defaults existing rows to
        # "generic" — encrypted_value's JSON reshape to {"value": ...} is handled
        # at read-time by secrets_router.py, not here, so no data migration needed)
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE user_secrets ADD COLUMN secret_type TEXT NOT NULL DEFAULT 'generic'"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create agent_secret_access table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS agent_secret_access (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    secret_id INTEGER NOT NULL REFERENCES user_secrets(id) ON DELETE CASCADE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create skill_files table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS skill_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id INTEGER NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    file_size INTEGER,
                    storage_path TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add parent_span_id to trace_spans if missing (links a nested/delegated
        # span, e.g. an agent_delegation hop, to its parent span)
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE trace_spans ADD COLUMN parent_span_id INTEGER REFERENCES trace_spans(id)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add kind to hitl_approvals if missing (tool_call | thread_continue)
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE hitl_approvals ADD COLUMN kind TEXT NOT NULL DEFAULT 'tool_call'"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create agent_thread_messages table if missing (one row per agent-to-agent
        # hop in an open multi-agent delegation thread — see team_delegation_tools.py)
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS agent_thread_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    user_turn_message_id INTEGER REFERENCES messages(id),
                    thread_id TEXT NOT NULL,
                    hop_index INTEGER NOT NULL,
                    from_agent_id INTEGER NOT NULL REFERENCES agents(id),
                    to_agent_id INTEGER NOT NULL REFERENCES agents(id),
                    content TEXT,
                    tool_calls_json TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()
        try:
            conn.execute(sqlalchemy.text(
                "CREATE INDEX IF NOT EXISTS ix_agent_thread_messages_session_id ON agent_thread_messages(session_id)"
            ))
            conn.execute(sqlalchemy.text(
                "CREATE INDEX IF NOT EXISTS ix_agent_thread_messages_thread_id ON agent_thread_messages(thread_id)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create team_members table if missing — a Team's roster is now rows here
        # (base agent + optional per-team overrides) rather than Team.agent_ids_json,
        # so the same reusable agent can be added to one team more than once in
        # different roles. The column stays on Team (removing it is disruptive for
        # no benefit) but is no longer read or written anywhere once backfilled.
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS team_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    position INTEGER NOT NULL,
                    override_name TEXT,
                    override_system_prompt TEXT,
                    override_tools_json TEXT,
                    override_mcp_servers_json TEXT,
                    override_skill_ids_json TEXT,
                    override_knowledge_base_ids_json TEXT,
                    can_delegate BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()
        try:
            conn.execute(sqlalchemy.text(
                "CREATE INDEX IF NOT EXISTS ix_team_members_team_id ON team_members(team_id)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # One-time backfill: every existing team's agent_ids_json entries become
        # TeamMember rows (position = array index, no overrides — pure inheritance,
        # identical behavior to today). Idempotent: only backfills a team that has
        # zero team_members rows yet, so this is safe to run on every startup.
        try:
            teams_needing_backfill = conn.execute(sqlalchemy.text("""
                SELECT t.id, t.agent_ids_json FROM teams t
                LEFT JOIN team_members tm ON tm.team_id = t.id
                WHERE tm.id IS NULL AND t.agent_ids_json IS NOT NULL
                GROUP BY t.id
            """)).fetchall()
            for team_id, agent_ids_json in teams_needing_backfill:
                try:
                    agent_ids = json.loads(agent_ids_json) if agent_ids_json else []
                except (TypeError, ValueError):
                    agent_ids = []
                for position, agent_id in enumerate(agent_ids):
                    conn.execute(sqlalchemy.text(
                        "INSERT INTO team_members (team_id, agent_id, position, can_delegate) VALUES (:team_id, :agent_id, :position, 1)"
                    ), {"team_id": team_id, "agent_id": int(agent_id), "position": position})
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

        # Add skill_ids_json to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN skill_ids_json TEXT"
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

        # Add is_model_created to tool_definitions if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE tool_definitions ADD COLUMN is_model_created BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add proposal_type and target_tool_id to tool_proposals if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE tool_proposals ADD COLUMN proposal_type TEXT DEFAULT 'create'"
            ))
            conn.commit()
        except Exception:
            conn.rollback()
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE tool_proposals ADD COLUMN target_tool_id INTEGER"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Deactivate pre-existing duplicate-named tool_definitions (same user_id + name,
        # both active) before enforcing uniqueness, keeping the oldest row of each group.
        try:
            conn.execute(sqlalchemy.text("""
                UPDATE tool_definitions
                SET is_active = 0
                WHERE is_active = 1
                  AND id NOT IN (
                    SELECT MIN(id) FROM tool_definitions
                    WHERE is_active = 1
                    GROUP BY user_id, name
                  )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Enforce one active tool name per user going forward. A plain UNIQUE(user_id, name)
        # index can't be used because rows are soft-deleted (is_active) rather than removed,
        # so we scope the uniqueness to active rows only via a partial index.
        try:
            conn.execute(sqlalchemy.text("""
                CREATE UNIQUE INDEX IF NOT EXISTS ux_tool_definitions_user_name_active
                ON tool_definitions (user_id, name)
                WHERE is_active = 1
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create agent_versions table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS agent_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    version_number INTEGER NOT NULL,
                    config_snapshot TEXT NOT NULL,
                    change_summary TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
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

        # Add cache_read_tokens to trace_spans if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE trace_spans ADD COLUMN cache_read_tokens INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add cache_creation_tokens to trace_spans if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE trace_spans ADD COLUMN cache_creation_tokens INTEGER NOT NULL DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add cost_usd to trace_spans if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE trace_spans ADD COLUMN cost_usd REAL"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add stop_reason to trace_spans if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE trace_spans ADD COLUMN stop_reason TEXT"
            ))
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

        # Add running_nodes_json to workflow_runs if missing (DAG: tracks in-flight node IDs)
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE workflow_runs ADD COLUMN running_nodes_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create eval_suites table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS eval_suites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    test_cases_json TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create eval_runs table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    suite_id INTEGER NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
                    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    agent_config_snapshot TEXT,
                    version_id INTEGER REFERENCES agent_versions(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    results_json TEXT,
                    score REAL,
                    total_cases INTEGER DEFAULT 0,
                    passed_cases INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create optimization_runs table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS optimization_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    status TEXT NOT NULL DEFAULT 'pending',
                    trace_session_ids TEXT,
                    trace_count INTEGER DEFAULT 0,
                    failure_patterns TEXT,
                    current_prompt TEXT,
                    proposed_prompt TEXT,
                    rationale TEXT,
                    eval_suite_id INTEGER REFERENCES eval_suites(id) ON DELETE SET NULL,
                    eval_run_id INTEGER REFERENCES eval_runs(id) ON DELETE SET NULL,
                    baseline_score REAL,
                    proposed_score REAL,
                    accepted_version_id INTEGER REFERENCES agent_versions(id) ON DELETE SET NULL,
                    rejected_reason TEXT,
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create audit_runs table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS audit_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    status TEXT NOT NULL DEFAULT 'pending',
                    seed_prompt TEXT NOT NULL,
                    probe_categories_json TEXT NOT NULL,
                    probes_per_category INTEGER DEFAULT 5,
                    judge_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    agent_config_snapshot TEXT,
                    results_json TEXT,
                    score REAL,
                    category_scores_json TEXT,
                    triggered_optimization_run_id INTEGER REFERENCES optimization_runs(id) ON DELETE SET NULL,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create inspection_runs table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS inspection_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    status TEXT NOT NULL DEFAULT 'pending',
                    prompt TEXT NOT NULL,
                    hf_model_id TEXT NOT NULL,
                    capture_config_json TEXT,
                    summary_json TEXT,
                    artifact_storage_path TEXT,
                    triggered_optimization_run_id INTEGER REFERENCES optimization_runs(id) ON DELETE SET NULL,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create finetune_runs table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS finetune_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    compute_backend TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    base_hf_model_id TEXT NOT NULL,
                    source_provider_id INTEGER REFERENCES llm_providers(id) ON DELETE SET NULL,
                    dataset_source_type TEXT NOT NULL,
                    dataset_session_ids_json TEXT,
                    dataset_storage_path TEXT,
                    dataset_row_count INTEGER,
                    dataset_filename TEXT,
                    hyperparams_json TEXT NOT NULL,
                    runpod_job_id TEXT,
                    runpod_estimated_cost_usd REAL,
                    runpod_actual_cost_usd REAL,
                    wsl2_job_id TEXT,
                    progress_json TEXT,
                    adapter_storage_path TEXT,
                    adapter_size_bytes INTEGER,
                    export_to_ollama BOOLEAN DEFAULT 0,
                    merged_gguf_storage_path TEXT,
                    merged_gguf_size_bytes INTEGER,
                    gguf_quantization TEXT,
                    ollama_model_tag TEXT,
                    created_provider_id INTEGER REFERENCES llm_providers(id) ON DELETE SET NULL,
                    created_agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    started_training_at DATETIME,
                    completed_at DATETIME,
                    auto_register_provider BOOLEAN DEFAULT 1,
                    auto_register_agent BOOLEAN DEFAULT 1
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create app_settings table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add memory_enabled to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN memory_enabled BOOLEAN DEFAULT 1"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add sandbox columns to agents if missing
        for col, typedef in [
            ("sandbox_enabled", "BOOLEAN DEFAULT 0"),
            ("sandbox_container_id", "TEXT"),
            ("sandbox_host_port", "INTEGER"),
        ]:
            try:
                conn.execute(sqlalchemy.text(f"ALTER TABLE agents ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                conn.rollback()

        # Add sandbox columns to teams if missing
        for col, typedef in [
            ("sandbox_enabled", "BOOLEAN DEFAULT 0"),
            ("sandbox_container_id", "TEXT"),
            ("sandbox_host_port", "INTEGER"),
        ]:
            try:
                conn.execute(sqlalchemy.text(f"ALTER TABLE teams ADD COLUMN {col} {typedef}"))
                conn.commit()
            except Exception:
                conn.rollback()

        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE eval_suites ADD COLUMN judge_agent_id INTEGER REFERENCES agents(id)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS whatsapp_channels (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER NOT NULL REFERENCES users(id),
                    agent_id        INTEGER NOT NULL REFERENCES agents(id),
                    name            TEXT NOT NULL,
                    wa_phone        TEXT,
                    status          TEXT NOT NULL DEFAULT 'disconnected',
                    allowed_jids    TEXT,
                    reject_message  TEXT,
                    auth_state_path TEXT,
                    is_active       BOOLEAN NOT NULL DEFAULT 1,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at      DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS wa_contact_sessions (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL REFERENCES whatsapp_channels(id),
                    wa_chat_id TEXT NOT NULL,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME,
                    UNIQUE(channel_id, wa_chat_id)
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Create prompt_vault table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS prompt_vault (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL REFERENCES users(id),
                    name        TEXT NOT NULL,
                    description TEXT,
                    content     TEXT NOT NULL,
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add prompt_vault_id to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN prompt_vault_id INTEGER"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add voice reply + TTS columns to whatsapp_channels if missing
        for col_sql in [
            "ALTER TABLE whatsapp_channels ADD COLUMN voice_reply_enabled BOOLEAN NOT NULL DEFAULT 0",
            "ALTER TABLE whatsapp_channels ADD COLUMN voice_reply_jids TEXT",
            "ALTER TABLE whatsapp_channels ADD COLUMN voice_reply_voice TEXT",
            "ALTER TABLE whatsapp_channels ADD COLUMN tts_backend TEXT",
            "ALTER TABLE whatsapp_channels ADD COLUMN voice_clone_audio_path TEXT",
            "ALTER TABLE whatsapp_channels ADD COLUMN voice_clone_ref_text TEXT",
        ]:
            try:
                conn.execute(sqlalchemy.text(col_sql))
                conn.commit()
            except Exception:
                conn.rollback()

        # Create vault_files table if missing
        try:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS vault_files (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL REFERENCES users(id),
                    name        TEXT NOT NULL,
                    folder      TEXT,
                    content     TEXT NOT NULL DEFAULT '',
                    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at  DATETIME
                )
            """))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add vault_file_ids_json to agents if missing
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE agents ADD COLUMN vault_file_ids_json TEXT"
            ))
            conn.commit()
        except Exception:
            conn.rollback()

        # Add agent_id to api_clients if missing (scopes a key to one agent;
        # NULL preserves today's account-wide key behavior)
        try:
            conn.execute(sqlalchemy.text(
                "ALTER TABLE api_clients ADD COLUMN agent_id INTEGER REFERENCES agents(id)"
            ))
            conn.commit()
        except Exception:
            conn.rollback()


# ── Module-level APScheduler job functions ────────────────────────────────────
# Must be at module scope (not closures) so APScheduler can pickle them for the
# MongoDB / SQLAlchemy job stores.

import logging as _sched_log
_sched_logger = _sched_log.getLogger(__name__)


async def _weekly_auto_optimize():
    """Trigger optimization for all agents (APScheduler weekly job)."""
    from datetime import timezone as _tz
    if DATABASE_TYPE == "mongo":
        from database_mongo import get_database as _get_mdb
        from models_mongo import OptimizationRunCollection as _ORC
        from optimizer import start_optimization_mongo
        try:
            _mdb = _get_mdb()
            _agents_coll = _mdb["agents"]
            async for _ag in _agents_coll.find({"is_active": True}):
                _aid = str(_ag["_id"])
                _uid = _ag.get("user_id", "")
                _doc = await _ORC.create(_mdb, {
                    "agent_id": _aid,
                    "user_id": _uid,
                    "status": "pending",
                    "trace_count": 0,
                })
                start_optimization_mongo(
                    run_id=str(_doc["_id"]),
                    agent_id=_aid,
                    user_id=_uid,
                    eval_suite_id=None,
                    min_traces=5,
                    max_traces=50,
                )
        except Exception as _e:
            _sched_logger.warning("Weekly auto-optimize (mongo) error: %s", _e)
    else:
        from optimizer import start_optimization_sqlite
        from models import Agent as _Agent, OptimizationRun as _OR
        from database import SessionLocal as _SL
        _db = _SL()
        try:
            for _ag in _db.query(_Agent).all():
                _run = _OR(
                    agent_id=_ag.id,
                    user_id=_ag.user_id,
                    status="pending",
                    trace_count=0,
                )
                _db.add(_run)
                _db.commit()
                _db.refresh(_run)
                start_optimization_sqlite(
                    run_id=_run.id,
                    agent_id=_ag.id,
                    user_id=_ag.user_id,
                    eval_suite_id=None,
                    min_traces=5,
                    max_traces=50,
                )
        except Exception as _e:
            _sched_logger.warning("Weekly auto-optimize (sqlite) error: %s", _e)
        finally:
            _db.close()


async def _daily_prune():
    """Prune old agent versions and terminal optimization runs (APScheduler daily job)."""
    from datetime import timedelta, timezone as _tz
    if DATABASE_TYPE == "mongo":
        from database_mongo import get_database as _get_mdb
        from models_mongo import AgentVersionCollection as _AVC, OptimizationRunCollection as _ORC
        try:
            _mdb = _get_mdb()
            from datetime import datetime as _dt
            _cutoff = _dt.now(_tz.utc) - timedelta(hours=72)
            _opt_cutoff = _dt.now(_tz.utc) - timedelta(days=30)
            async for _ag in _mdb["agents"].find({}, {"_id": 1}):
                await _AVC.prune_old(_mdb, str(_ag["_id"]), _cutoff)
            await _ORC.prune_old(_mdb, _opt_cutoff)
        except Exception as _e:
            _sched_logger.warning("Daily prune (mongo) error: %s", _e)
    else:
        from models import AgentVersion as _AV, OptimizationRun as _OR, Agent as _Agent
        from database import SessionLocal as _SL
        from datetime import datetime as _dt
        _db = _SL()
        try:
            _cutoff = _dt.now() - timedelta(hours=72)
            for _ag in _db.query(_Agent).all():
                _latest = _db.query(_AV).filter(
                    _AV.agent_id == _ag.id
                ).order_by(_AV.version_number.desc()).first()
                if _latest:
                    _db.query(_AV).filter(
                        _AV.agent_id == _ag.id,
                        _AV.created_at < _cutoff,
                        _AV.id != _latest.id,
                    ).delete(synchronize_session=False)
            _opt_cutoff = _dt.now() - timedelta(days=30)
            _db.query(_OR).filter(
                _OR.status.in_(["accepted", "rejected", "failed"]),
                _OR.created_at < _opt_cutoff,
            ).delete(synchronize_session=False)
            _db.commit()
        except Exception as _e:
            _sched_logger.warning("Daily prune (sqlite) error: %s", _e)
            _db.rollback()
        finally:
            _db.close()


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


async def _load_pending_async_jobs():
    """Re-register APScheduler poll jobs for all pending AsyncJob records on startup.
    Without this, jobs created before a server restart would never be re-checked
    again (APScheduler's in-memory trigger registration doesn't survive restarts
    even though the jobstore itself persists the schedule metadata for cron jobs;
    for on-the-fly IntervalTrigger jobs we re-add them explicitly here)."""
    from scheduler import scheduler as _sched
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        if DATABASE_TYPE == "mongo":
            from async_job_poller import poll_async_job_mongo
            mongo_db = get_database()
            jobs = await AsyncJobCollection.find_all_pending(mongo_db)
            for j in jobs:
                job_id = str(j["_id"])
                try:
                    _sched.add_job(
                        poll_async_job_mongo,
                        trigger=IntervalTrigger(seconds=j.get("interval_seconds", 30)),
                        args=[job_id],
                        id=f"async_job_{job_id}",
                        replace_existing=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Could not restore async job {job_id}: {e}")
        else:
            from async_job_poller import poll_async_job_sqlite
            from models import AsyncJob
            db = get_db_sync()
            try:
                jobs = db.query(AsyncJob).filter(AsyncJob.status == "pending").all()
                for j in jobs:
                    try:
                        _sched.add_job(
                            poll_async_job_sqlite,
                            trigger=IntervalTrigger(seconds=j.interval_seconds),
                            args=[j.id],
                            id=f"async_job_{j.id}",
                            replace_existing=True,
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Could not restore async job {j.id}: {e}")
            finally:
                db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to load pending async jobs: {e}")


_FINETUNE_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


async def _load_pending_finetune_runs():
    """Re-register the interval poll for every non-terminal FineTuneRun on
    startup, same restart-survival reasoning as _load_pending_async_jobs:
    APScheduler's on-the-fly IntervalTrigger jobs don't survive a process
    restart on their own, so every in-flight fine-tune run (local_wsl2 or
    runpod) needs its poll job re-added here or it would silently stop
    being checked forever."""
    from scheduler import scheduler as _sched
    from apscheduler.triggers.interval import IntervalTrigger
    try:
        if DATABASE_TYPE == "mongo":
            from finetune_poller import poll_finetune_run_mongo
            from models_mongo import FineTuneRunCollection
            mongo_db = get_database()
            collection = mongo_db[FineTuneRunCollection.collection_name]
            cursor = collection.find({"status": {"$nin": list(_FINETUNE_TERMINAL_STATUSES)}})
            runs = await cursor.to_list(length=200)
            for r in runs:
                run_id = str(r["_id"])
                try:
                    _sched.add_job(
                        poll_finetune_run_mongo,
                        trigger=IntervalTrigger(seconds=20),
                        args=[run_id],
                        id=f"finetune_run_{run_id}",
                        replace_existing=True,
                    )
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Could not restore finetune run {run_id}: {e}")
        else:
            from finetune_poller import poll_finetune_run_sqlite
            from models import FineTuneRun
            db = get_db_sync()
            try:
                runs = db.query(FineTuneRun).filter(FineTuneRun.status.notin_(_FINETUNE_TERMINAL_STATUSES)).all()
                for r in runs:
                    try:
                        _sched.add_job(
                            poll_finetune_run_sqlite,
                            trigger=IntervalTrigger(seconds=20),
                            args=[r.id],
                            id=f"finetune_run_{r.id}",
                            replace_existing=True,
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"Could not restore finetune run {r.id}: {e}")
            finally:
                db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to load pending finetune runs: {e}")


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
        await AgentThreadMessageCollection.create_indexes(db)
        await TeamMemberCollection.create_indexes(db)
        await ToolDefinitionCollection.create_indexes(db)
        await SkillCollection.create_indexes(db)
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
        await WhatsAppChannelCollection.create_indexes(db)
        await WAContactSessionCollection.create_indexes(db)
        await AsyncJobCollection.create_indexes(db)
        await WorkflowApprovalCollection.create_indexes(db)
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

        # One-time backfill: every existing team's agent_ids_json entries become
        # TeamMember docs (position = array index, no overrides — pure inheritance,
        # identical behavior to today). Idempotent: only backfills a team with zero
        # team_members docs yet, so this is safe to run on every startup.
        async for team in db.teams.find({"agent_ids_json": {"$exists": True, "$ne": None}}):
            try:
                existing = await TeamMemberCollection.find_by_team(db, str(team["_id"]))
                if existing:
                    continue
                agent_ids_raw = team.get("agent_ids_json")
                agent_ids = json.loads(agent_ids_raw) if isinstance(agent_ids_raw, str) else (agent_ids_raw or [])
                for position, agent_id in enumerate(agent_ids):
                    await TeamMemberCollection.create(db, {
                        "team_id": str(team["_id"]), "agent_id": str(agent_id), "position": position,
                    })
            except Exception:
                pass

    # Start APScheduler
    from scheduler import scheduler as _scheduler, configure_scheduler
    configure_scheduler()
    await _load_active_schedules()
    await _load_pending_async_jobs()
    await _load_pending_finetune_runs()

    # ── Maintenance jobs (module-level functions so APScheduler can pickle them) ─
    from apscheduler.triggers.cron import CronTrigger as _CronTrigger

    # Weekly auto-sweep: Monday 02:00
    _scheduler.add_job(
        _weekly_auto_optimize,
        trigger=_CronTrigger(day_of_week="mon", hour=2, minute=0),
        id="weekly_auto_optimize",
        replace_existing=True,
    )
    # Daily prune: 03:00 every day
    _scheduler.add_job(
        _daily_prune,
        trigger=_CronTrigger(hour=3, minute=0),
        id="daily_prune",
        replace_existing=True,
    )

    _scheduler.start()

    # Optional ngrok tunnel — only starts if ENABLE_NGROK_TUNNEL is set; see
    # tunnel.py. Lets an agent's public API endpoint be reached from outside
    # this self-hosted instance's local network without any other setup.
    from tunnel import start_tunnel, stop_tunnel
    import os as _os
    start_tunnel(int(_os.getenv("PORT", "8000")))

    # Warm the RAG embedding model in the background so the first KB/chat
    # document upload doesn't pay the (sometimes multi-minute, first-run
    # download) load cost inline and look like a hang. Best-effort — if this
    # fails, the model just lazy-loads on first real use as before.
    from rag_service import RAGService
    asyncio.get_event_loop().run_in_executor(None, RAGService.preload_embedding_model)

    yield

    # Shutdown APScheduler
    _scheduler.shutdown(wait=False)
    stop_tunnel()
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
app.include_router(agent_api_router)
app.include_router(public_api_router)
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
app.include_router(versions_router)
app.include_router(eval_router)
app.include_router(auditor_router)
app.include_router(inspector_router)
app.include_router(finetune_router)
app.include_router(optimizer_router)
app.include_router(settings_router)
app.include_router(sandbox_router)
app.include_router(analytics_router)
app.include_router(whatsapp_router)
app.include_router(prompt_vault_router)
app.include_router(skills_router)
app.include_router(vault_router)


@app.get("/tunnel/status")
async def tunnel_status(current_user: TokenData = Depends(get_current_user)):
    """Public-API tunnel status for the frontend's API-access dialog: whether
    an ngrok tunnel is enabled/running, and its current public URL if so."""
    from tunnel import is_enabled, get_public_url
    return {"enabled": is_enabled(), "public_url": get_public_url()}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
