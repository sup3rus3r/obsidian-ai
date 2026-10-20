from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, Float
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String, unique=True, index=True, nullable=False)
    email           = Column(String, unique=True, index=True, nullable=False)
    role            = Column(String, index=True, nullable=False)
    hashed_password  = Column(String, nullable=False)
    permissions_json = Column(Text, nullable=True)
    totp_secret      = Column(String, nullable=True)
    totp_enabled     = Column(Boolean, default=False, nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


class APIClient(Base):
    """API clients for external access with client_id/secret authentication.
    agent_id is nullable: NULL means an account-wide key (today's behavior,
    unchanged); set means the key is scoped to exactly that one agent and is
    the only kind accepted by the public single-agent invoke endpoint."""
    __tablename__ = "api_clients"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    client_id     = Column(String, unique=True, index=True, nullable=False)
    hashed_secret = Column(String, nullable=False)
    created_by    = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id      = Column(Integer, ForeignKey("agents.id"), nullable=True)
    is_active     = Column(Boolean, default=True, nullable=False)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class LLMProvider(Base):
    """Configured LLM provider endpoints."""
    __tablename__ = "llm_providers"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    name          = Column(String, nullable=False)
    provider_type = Column(String, nullable=False)        # openai | anthropic | google | ollama | openrouter | custom
    base_url      = Column(String, nullable=True)
    api_key       = Column(String, nullable=True)          # encrypted at rest
    secret_id     = Column(Integer, nullable=True)         # FK to user_secrets (optional)
    model_id      = Column(String, nullable=True)
    is_active     = Column(Boolean, default=True)
    config_json   = Column(Text, nullable=True)            # JSON: {temperature, max_tokens, ...}
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())


class Agent(Base):
    """An AI agent configuration."""
    __tablename__ = "agents"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    name          = Column(String, nullable=False)
    description   = Column(Text, nullable=True)
    system_prompt = Column(Text, nullable=True)
    provider_id   = Column(Integer, ForeignKey("llm_providers.id"), nullable=True)
    tools_json    = Column(Text, nullable=True)            # JSON array of tool definition IDs
    mcp_servers_json = Column(Text, nullable=True)         # JSON array of MCP server IDs
    knowledge_base_ids_json = Column(Text, nullable=True)  # JSON array of knowledge base IDs
    vault_file_ids_json = Column(Text, nullable=True)      # JSON array of vault file IDs (full-content prompt injection)
    skill_ids_json = Column(Text, nullable=True)            # JSON array of skill IDs (Claude agents only)
    model_id      = Column(String, nullable=True)              # model to use, e.g. "claude-sonnet-5"
    hitl_confirmation_tools_json = Column(Text, nullable=True)  # JSON array of tool names requiring HITL
    allow_tool_creation = Column(Boolean, default=False, nullable=False)  # agent can propose new tools
    memory_enabled       = Column(Boolean, default=True, nullable=False)   # long-term memory toggle
    sandbox_enabled      = Column(Boolean, default=False, nullable=False)  # Docker sandbox toggle
    sandbox_container_id = Column(String, nullable=True)                   # running container ID
    sandbox_host_port    = Column(Integer, nullable=True)                  # mapped host port
    prompt_vault_id = Column(Integer, nullable=True)               # tracks source vault entry (if loaded from vault)
    config_json   = Column(Text, nullable=True)            # JSON: {temperature, max_tokens, ...}
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())


class Team(Base):
    """A multi-agent team configuration."""
    __tablename__ = "teams"

    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=False)
    name           = Column(String, nullable=False)
    description    = Column(Text, nullable=True)
    mode           = Column(String, default="coordinate")  # coordinate | route | collaborate
    agent_ids_json = Column(Text, nullable=False)          # JSON array of agent IDs
    sandbox_enabled      = Column(Boolean, default=False, nullable=False)  # shared Docker sandbox
    sandbox_container_id = Column(String, nullable=True)
    sandbox_host_port    = Column(Integer, nullable=True)
    config_json    = Column(Text, nullable=True)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())


class Session(Base):
    """A chat session (conversation thread)."""
    __tablename__ = "sessions"

    id                  = Column(Integer, primary_key=True, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False)
    title               = Column(String, nullable=True)
    entity_type         = Column(String, nullable=False)           # agent | team
    entity_id           = Column(Integer, nullable=False)
    is_active           = Column(Boolean, default=True)
    total_input_tokens  = Column(Integer, default=0, nullable=False)
    total_output_tokens = Column(Integer, default=0, nullable=False)
    memory_processed    = Column(Boolean, default=False, nullable=False)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())


class Message(Base):
    """A single message in a session."""
    __tablename__ = "messages"

    id               = Column(Integer, primary_key=True, index=True)
    session_id       = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    role             = Column(String, nullable=False)       # user | assistant | system | tool
    content          = Column(Text, nullable=True)
    agent_id         = Column(Integer, ForeignKey("agents.id"), nullable=True)
    tool_calls_json  = Column(Text, nullable=True)          # JSON: [{name, arguments, result}]
    reasoning_json   = Column(Text, nullable=True)          # JSON: reasoning/thinking steps
    metadata_json    = Column(Text, nullable=True)          # JSON: {model, tokens_used, latency_ms}
    attachments_json = Column(Text, nullable=True)          # JSON: [{filename, media_type, file_type, file_id}]
    rating           = Column(String, nullable=True)        # "up" | "down" | None
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


class FileAttachment(Base):
    """A file uploaded in a chat session."""
    __tablename__ = "file_attachments"

    id            = Column(Integer, primary_key=True, index=True)
    session_id    = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    message_id    = Column(Integer, ForeignKey("messages.id"), nullable=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename      = Column(String, nullable=False)
    media_type    = Column(String, nullable=False)         # e.g. "image/png", "application/pdf"
    file_type     = Column(String, nullable=False)         # "image" | "document"
    file_size     = Column(Integer, nullable=True)         # bytes
    storage_path  = Column(String, nullable=True)          # filesystem path (relative to uploads/)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class Workflow(Base):
    """A workflow definition -- a sequence of agent steps/tasks."""
    __tablename__ = "workflows"

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    name          = Column(String, nullable=False)
    description   = Column(Text, nullable=True)
    steps_json    = Column(Text, nullable=False)           # JSON array: [{agent_id, task, order, config}]
    config_json   = Column(Text, nullable=True)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())


class WorkflowRun(Base):
    """A single execution of a workflow."""
    __tablename__ = "workflow_runs"

    id            = Column(Integer, primary_key=True, index=True)
    workflow_id   = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id    = Column(Integer, ForeignKey("sessions.id"), nullable=True)
    status        = Column(String, default="running")    # running | completed | failed | cancelled
    current_step  = Column(Integer, default=0)
    steps_json    = Column(Text, nullable=True)          # JSON: [{order, agent_id, agent_name, task, status, output, started_at, completed_at, error}]
    input_text    = Column(Text, nullable=True)
    final_output  = Column(Text, nullable=True)
    error         = Column(Text, nullable=True)
    started_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), nullable=True)


class ToolDefinition(Base):
    """A reusable tool/function definition.

    Uniqueness of (user_id, name) among active rows is enforced by the partial
    index `ux_tool_definitions_user_name_active` created in main.py's SQLite
    migration block (not expressible as a plain Column constraint since rows
    are soft-deleted via is_active rather than removed).
    """
    __tablename__ = "tool_definitions"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    name            = Column(String, nullable=False)
    description     = Column(Text, nullable=True)
    parameters_json = Column(Text, nullable=False)         # JSON Schema for parameters
    handler_type    = Column(String, default="http")       # http | python | builtin
    handler_config  = Column(Text, nullable=True)          # JSON: {url, method, headers} or {module, function}
    requires_confirmation = Column(Boolean, default=False, nullable=False)
    is_active       = Column(Boolean, default=True)
    is_model_created = Column(Boolean, default=False, nullable=False)  # True when created via agent tool proposal
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class MCPServer(Base):
    """A configured MCP server endpoint."""
    __tablename__ = "mcp_servers"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    name            = Column(String, nullable=False)
    description     = Column(Text, nullable=True)
    transport_type  = Column(String, nullable=False)        # stdio | sse
    command         = Column(String, nullable=True)          # stdio: e.g. "npx", "python", "uvx"
    args_json       = Column(Text, nullable=True)            # stdio: JSON array of arguments
    env_json        = Column(Text, nullable=True)            # stdio: JSON object of env vars
    url             = Column(String, nullable=True)          # sse: server URL
    headers_json    = Column(Text, nullable=True)            # sse: JSON object of headers
    is_active       = Column(Boolean, default=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())


class Skill(Base):
    """A reusable Claude Skill: a named instruction bundle (SKILL.md-style) that
    gets injected into an agent's system prompt when attached. Modeled on
    Anthropic's Agent Skills concept (progressive-disclosure instruction
    bundles) but implemented as plain prompt injection rather than their
    hosted code-execution container — so it works without extra
    infrastructure, while still only being meaningful for Claude models
    (gated at the agent-config layer, not here)."""
    __tablename__ = "skills"

    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    name         = Column(String, nullable=False)
    description  = Column(Text, nullable=True)   # short summary shown before the skill is "loaded"
    instructions = Column(Text, nullable=False)  # full SKILL.md-style body injected when active
    is_active    = Column(Boolean, default=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())


class KnowledgeBase(Base):
    """A named collection of documents/text used for RAG."""
    __tablename__ = "knowledge_bases"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_shared   = Column(Boolean, default=False)   # admin-created, visible to all users
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())


class KnowledgeBaseDocument(Base):
    """A single document (text or file) within a knowledge base."""
    __tablename__ = "kb_documents"

    id           = Column(Integer, primary_key=True, index=True)
    kb_id        = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False)
    doc_type     = Column(String, nullable=False)    # "text" | "file"
    name         = Column(String, nullable=False)    # display name
    content_text = Column(Text, nullable=True)       # for text type
    file_id      = Column(String, nullable=True)     # filesystem path or GridFS ObjectId
    filename     = Column(String, nullable=True)
    media_type   = Column(String, nullable=True)
    indexed      = Column(Boolean, default=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())


class WorkflowSchedule(Base):
    """A cron-based schedule for automatic workflow execution."""
    __tablename__ = "workflow_schedules"

    id          = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    name        = Column(String, nullable=False)
    cron_expr   = Column(String, nullable=False)       # e.g. "0 9 * * 1-5"
    input_text  = Column(Text, nullable=True)
    is_active   = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())


class UserSecret(Base):
    """User-managed secrets, encrypted at rest. secret_type picks a field
    schema (see secret_types.py) — encrypted_value is a JSON object mapping
    each of that type's field names to an independently-Fernet-encrypted
    string, e.g. {"number": "gAAAAA...", "cvv": "gAAAAA..."} for credit_card,
    or {"value": "gAAAAA..."} for the original generic single-value shape.
    A secret existing here grants no tool-call access on its own — see
    AgentSecretAccess."""
    __tablename__ = "user_secrets"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    name            = Column(String, nullable=False)
    secret_type     = Column(String, default="generic", nullable=False)   # generic | credit_card | login
    encrypted_value = Column(Text, nullable=False)
    description     = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())


class AgentSecretAccess(Base):
    """Per-agent allowlist: which secrets an agent may reference via the
    {{secrets.<name>.<field>}} placeholder syntax (secret_placeholder.py).
    A real join table, not a JSON array on Agent, because this is a security
    boundary (fails closed if absent) rather than a UI convenience list."""
    __tablename__ = "agent_secret_access"

    id          = Column(Integer, primary_key=True, index=True)
    agent_id    = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    secret_id   = Column(Integer, ForeignKey("user_secrets.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class VaultFile(Base):
    """A user-managed Markdown file (Obsidian-style vault note)."""
    __tablename__ = "vault_files"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    name        = Column(String, nullable=False)        # display name, e.g. "Project Notes"
    folder      = Column(String, nullable=True)          # optional folder path, e.g. "research/2026"
    content     = Column(Text, nullable=False, default="")
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())


class PromptVault(Base):
    """User-managed reusable prompt templates."""
    __tablename__ = "prompt_vault"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    content     = Column(Text, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())


class HITLApproval(Base):
    """A pending or resolved human-in-the-loop tool approval request."""
    __tablename__ = "hitl_approvals"

    id                  = Column(Integer, primary_key=True, index=True)
    session_id          = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    tool_call_id        = Column(String, nullable=False)
    tool_name           = Column(String, nullable=False)
    tool_arguments_json = Column(Text, nullable=True)
    status              = Column(String, default="pending", nullable=False)  # pending | approved | denied
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at         = Column(DateTime(timezone=True), nullable=True)


class ToolProposal(Base):
    """A tool definition proposed by an agent, awaiting user approval."""
    __tablename__ = "tool_proposals"

    id                  = Column(Integer, primary_key=True, index=True)
    session_id          = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    tool_call_id        = Column(String, nullable=False)        # LLM tool call id
    name                = Column(String, nullable=False)
    description         = Column(Text, nullable=True)
    handler_type        = Column(String, nullable=False)        # python | http
    parameters_json     = Column(Text, nullable=False)          # JSON Schema
    handler_config_json = Column(Text, nullable=True)           # JSON
    proposal_type       = Column(String, default="create", nullable=False)   # create | edit
    target_tool_id      = Column(Integer, nullable=True)        # for edit proposals: ID of the ToolDefinition to update
    status              = Column(String, default="pending", nullable=False)  # pending | approved | rejected
    created_tool_id     = Column(Integer, nullable=True)        # ID of the created ToolDefinition if approved (create proposals)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at         = Column(DateTime(timezone=True), nullable=True)


class AsyncJob(Base):
    """
    A long-running MCP tool job the agent asked to be re-checked on a schedule
    (e.g. a design generation job started by one tool and finished by another).
    Polled in the background by APScheduler; on completion a new assistant
    Message is appended to the session and the job is marked resolved so the
    pending-jobs notification badge can pick it up.
    """
    __tablename__ = "async_jobs"

    id                   = Column(Integer, primary_key=True, index=True)
    session_id           = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    agent_id             = Column(Integer, ForeignKey("agents.id"), nullable=True)
    mcp_server_id        = Column(Integer, ForeignKey("mcp_servers.id"), nullable=False)
    description          = Column(String, nullable=False)       # human-readable, shown in the badge
    poll_tool_name       = Column(String, nullable=False)        # unprefixed MCP tool name to re-invoke
    poll_arguments_json  = Column(Text, nullable=True)           # JSON args for the poll tool call
    interval_seconds     = Column(Integer, default=30, nullable=False)
    max_polls            = Column(Integer, default=120, nullable=False)  # safety cap (~1hr at 30s default)
    poll_count           = Column(Integer, default=0, nullable=False)
    status               = Column(String, default="pending", nullable=False)  # pending | completed | failed | expired
    last_result           = Column(Text, nullable=True)
    error                = Column(Text, nullable=True)
    seen                 = Column(Boolean, default=False, nullable=False)  # dismissed from the badge
    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at          = Column(DateTime(timezone=True), nullable=True)


class WorkflowApproval(Base):
    """A pending or resolved human-in-the-loop approval for a DAG workflow's
    'approval' node — the workflow equivalent of HITLApproval (chat tool-call
    approvals). Mirrors that pattern: a pending row + an in-memory
    asyncio.Event the executor waits on (see dag_executor.workflow_hitl_events)."""
    __tablename__ = "workflow_approvals"

    id                  = Column(Integer, primary_key=True, index=True)
    workflow_run_id     = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False)
    node_id             = Column(String, nullable=False)
    prompt              = Column(Text, nullable=True)
    status              = Column(String, default="pending", nullable=False)  # pending | approved | denied | expired
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at         = Column(DateTime(timezone=True), nullable=True)


class AgentVersion(Base):
    """A point-in-time snapshot of an agent's configuration."""
    __tablename__ = "agent_versions"

    id              = Column(Integer, primary_key=True, index=True)
    agent_id        = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    version_number  = Column(Integer, nullable=False)       # monotonically increasing per agent
    config_snapshot = Column(Text, nullable=False)          # full JSON dump of the agent at that point
    change_summary  = Column(String, nullable=True)         # e.g. "Manual edit", "Rollback to v2"
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class AgentMemory(Base):
    """A distilled memory fact extracted from a past conversation with an agent."""
    __tablename__ = "agent_memories"

    id         = Column(Integer, primary_key=True, index=True)
    agent_id   = Column(Integer, ForeignKey("agents.id"), nullable=False)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    key        = Column(String, nullable=False)      # semantic key, e.g. "preferred_language"
    value      = Column(Text, nullable=False)        # human-readable fact, e.g. "Python"
    category   = Column(String, nullable=False)      # preference | context | decision | correction
    confidence = Column(Float, default=1.0, nullable=False)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=True)  # source session
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TraceSpan(Base):
    """A single observable unit of work within a session or workflow run."""
    __tablename__ = "trace_spans"

    id                    = Column(Integer, primary_key=True, index=True)
    session_id            = Column(Integer, ForeignKey("sessions.id"), nullable=True, index=True)
    workflow_run_id       = Column(Integer, ForeignKey("workflow_runs.id"), nullable=True, index=True)
    message_id            = Column(Integer, ForeignKey("messages.id"), nullable=True)
    span_type             = Column(String, nullable=False)               # llm_call | tool_call | mcp_call | workflow_step
    name                  = Column(String, nullable=False)               # model name OR tool name
    input_tokens          = Column(Integer, default=0, nullable=False)
    output_tokens         = Column(Integer, default=0, nullable=False)
    cache_read_tokens     = Column(Integer, default=0, nullable=False)   # Anthropic prompt cache read tokens
    cache_creation_tokens = Column(Integer, default=0, nullable=False)   # Anthropic prompt cache write tokens
    cost_usd              = Column(Float, nullable=True)                 # estimated cost in USD
    duration_ms           = Column(Integer, default=0, nullable=False)
    status                = Column(String, default="success", nullable=False)  # success | error
    stop_reason           = Column(String, nullable=True)                # end_turn | max_tokens | tool_use | stop
    input_data            = Column(Text, nullable=True)                  # JSON string
    output_data           = Column(Text, nullable=True)                  # JSON string
    sequence              = Column(Integer, default=0, nullable=False)   # ordering within a generator invocation
    round_number          = Column(Integer, default=0, nullable=False)   # tool loop round index
    created_at            = Column(DateTime(timezone=True), server_default=func.now())


class EvalSuite(Base):
    """A named collection of test cases for evaluating an agent."""
    __tablename__ = "eval_suites"

    id               = Column(Integer, primary_key=True, index=True)
    user_id          = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id         = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    judge_agent_id   = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    name             = Column(String, nullable=False)
    description      = Column(String, nullable=True)
    # JSON array: [{id, input, expected_output, grading_method, weight}]
    test_cases_json  = Column(Text, nullable=False, default="[]")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())


class EvalRun(Base):
    """A single execution of an EvalSuite against an agent."""
    __tablename__ = "eval_runs"

    id                    = Column(Integer, primary_key=True, index=True)
    suite_id              = Column(Integer, ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id              = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_config_snapshot = Column(Text, nullable=True)  # JSON snapshot of agent config used
    version_id            = Column(Integer, ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True)
    status                = Column(String, default="pending")  # pending | running | completed | failed
    # JSON array: [{case_id, input, expected, actual_output, passed, score, reasoning}]
    results_json          = Column(Text, nullable=True)
    score                 = Column(Float, nullable=True)        # 0.0–1.0 overall pass rate
    total_cases           = Column(Integer, default=0)
    passed_cases          = Column(Integer, default=0)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    completed_at          = Column(DateTime(timezone=True), nullable=True)


class OptimizationRun(Base):
    """A prompt optimization pipeline run for an agent."""
    __tablename__ = "optimization_runs"

    id                  = Column(Integer, primary_key=True, index=True)
    agent_id            = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False)
    status              = Column(String, default="pending")
    # pending | analyzing | proposing | validating | awaiting_review | accepted | rejected | failed

    # Trace analysis
    trace_session_ids   = Column(Text, nullable=True)       # JSON list of session IDs sampled
    trace_count         = Column(Integer, default=0)
    failure_patterns    = Column(Text, nullable=True)       # JSON: LLM-extracted failure categories

    # Proposal
    current_prompt      = Column(Text, nullable=True)       # snapshot of prompt at time of analysis
    proposed_prompt     = Column(Text, nullable=True)
    rationale           = Column(Text, nullable=True)

    # Validation
    eval_suite_id       = Column(Integer, ForeignKey("eval_suites.id", ondelete="SET NULL"), nullable=True)
    eval_run_id         = Column(Integer, ForeignKey("eval_runs.id", ondelete="SET NULL"), nullable=True)
    baseline_score      = Column(Float, nullable=True)
    proposed_score      = Column(Float, nullable=True)

    # Outcome
    accepted_version_id = Column(Integer, ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True)
    rejected_reason     = Column(String, nullable=True)
    error_message       = Column(Text, nullable=True)

    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    completed_at        = Column(DateTime(timezone=True), nullable=True)


class AuditRun(Base):
    """A behavioral consistency audit run for an agent — black-box probe
    testing (paraphrase/order/adversarial/repeat/CoT-alignment), not
    interpretability. See auditor_engine.py."""
    __tablename__ = "audit_runs"

    id                  = Column(Integer, primary_key=True, index=True)
    agent_id            = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False)
    status              = Column(String, default="pending")
    # pending | generating_probes | running_probes | scoring | completed | failed | cancelled

    seed_prompt         = Column(Text, nullable=False)
    probe_categories_json = Column(Text, nullable=False)   # JSON list, e.g. ["paraphrase","order","adversarial","repeat","cot_alignment"]
    probes_per_category = Column(Integer, default=5)
    judge_agent_id      = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    agent_config_snapshot = Column(Text, nullable=True)    # JSON snapshot of agent config audited
    # JSON array: [{category, original_prompt, variant_prompt, original_response,
    #               variant_response, consistency_score, passed, disagreement_type,
    #               reasoning, cot_text, cot_alignment_flag}]
    results_json        = Column(Text, nullable=True)
    score                = Column(Float, nullable=True)     # overall 0.0–1.0
    category_scores_json = Column(Text, nullable=True)      # JSON: {"paraphrase": 0.8, ...}

    triggered_optimization_run_id = Column(Integer, ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True)

    error               = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    completed_at        = Column(DateTime(timezone=True), nullable=True)


class InspectionRun(Base):
    """A local-model interpretability inspection run — activation/attention
    capture + raw logit-lens probing against a raw HF checkpoint, run via the
    separate inspector_service (own process/venv, NOT in-process, NOT via
    Ollama — see backend/inspector_service/README.md). This is NOT solving
    interpretability: see inspector_engine.py's module docstring and the
    Inspector page's limits banner for what these numbers can and cannot
    validly claim (attention weight != causation, logit lens is one specific
    linear projection with known basis-drift limitations, single-neuron
    activations are not presumed interpretable features, a single prompt's
    run is not a general statement about the model)."""
    __tablename__ = "inspection_runs"

    id                  = Column(Integer, primary_key=True, index=True)
    agent_id            = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False)
    status              = Column(String, default="pending")
    # pending | loading_model | capturing | processing | completed | failed | cancelled

    prompt              = Column(Text, nullable=False)
    hf_model_id         = Column(String, nullable=False)   # user-supplied HF repo id/path — NOT the agent's provider model_id
    capture_config_json = Column(Text, nullable=True)      # JSON: {layers, capture_attention, capture_residual, logit_lens_topk, max_seq_len}

    # Summary data — small enough to inline, same convention as AuditRun.results_json.
    # JSON: {token_count, truncated, per_layer: [{layer, residual_norm,
    #        logit_lens_top_tokens, attention_entropy_by_head, num_heads}]}
    summary_json        = Column(Text, nullable=True)

    # Full-resolution tensors (only for explicitly-requested layers) are too
    # large for a TEXT column — stored as a safetensors blob via file_storage.py,
    # same pattern as FileAttachment.storage_path, not inlined.
    artifact_storage_path = Column(String, nullable=True)

    triggered_optimization_run_id = Column(Integer, ForeignKey("optimization_runs.id", ondelete="SET NULL"), nullable=True)

    error               = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    completed_at        = Column(DateTime(timezone=True), nullable=True)


class FineTuneRun(Base):
    """A LoRA/QLoRA fine-tuning run for a local model. Two compute backends
    share this one row shape — see compute_backend and the status value set
    below, which differ per backend. Training itself never runs in this
    process: 'local_wsl2' delegates to finetune_service running inside WSL2
    (own venv, same user-started lifecycle as Ollama/inspector_service — see
    backend/finetune_service/README.md), 'runpod' delegates to a RunPod
    serverless endpoint via runpod_client.py. This row is the only source of
    truth for progress/cancellation; both backends are polled on an interval
    via finetune_poller.py and must survive a server restart."""
    __tablename__ = "finetune_runs"

    id                  = Column(Integer, primary_key=True, index=True)
    agent_id            = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False)

    compute_backend     = Column(String, nullable=False)   # "runpod" | "local_wsl2"
    status              = Column(String, default="pending")
    # pending | preparing_dataset | submitting | provisioning | training |
    # merging | converting_gguf | quantizing | registering | completed |
    # failed | cancelled
    # ("provisioning" is runpod-only cold start; merging/converting_gguf/
    # quantizing are skipped entirely if export_to_ollama=False)

    base_hf_model_id    = Column(String, nullable=False)   # HF repo id/path of the base model being fine-tuned
    source_provider_id  = Column(Integer, ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)

    # --- Dataset ---
    dataset_source_type = Column(String, nullable=False)   # "session_export" | "uploaded_file"
    dataset_session_ids_json = Column(Text, nullable=True)  # JSON list of Session.id used, if session_export
    dataset_storage_path = Column(String, nullable=True)    # FileStorageService path/GridFS id of the normalized ChatML JSONL
    dataset_row_count    = Column(Integer, nullable=True)
    dataset_filename     = Column(String, nullable=True)    # original uploaded filename, if uploaded_file

    # --- Hyperparameters (JSON blob, same convention as capture_config_json) ---
    hyperparams_json    = Column(Text, nullable=False)
    # JSON: {lora_r, lora_alpha, lora_dropout, target_modules, learning_rate,
    #        num_epochs, per_device_batch_size, gradient_accumulation_steps,
    #        max_seq_len, quantization ("4bit"|"8bit"|"none"), seed}

    # --- Backend-specific job tracking ---
    runpod_job_id        = Column(String, nullable=True)   # RunPod endpoint job id (runpod backend)
    runpod_estimated_cost_usd = Column(Float, nullable=True)  # pre-run estimate shown to user
    runpod_actual_cost_usd    = Column(Float, nullable=True)  # computed from runtime * $/hr on completion
    wsl2_job_id           = Column(String, nullable=True)   # finetune_service's own job id (local_wsl2 backend)

    # --- Progress (polled, small enough to inline) ---
    progress_json        = Column(Text, nullable=True)
    # JSON: {current_step, total_steps, current_epoch, total_epochs, loss, eta_seconds}

    # --- Output artifacts ---
    adapter_storage_path  = Column(String, nullable=True)  # LoRA adapter safetensors (+ adapter_config.json), zipped
    adapter_size_bytes    = Column(Integer, nullable=True)
    export_to_ollama      = Column(Boolean, default=False) # whether the merge->GGUF->quantize->ollama pipeline runs at all
    merged_gguf_storage_path = Column(String, nullable=True)  # only set if export_to_ollama
    merged_gguf_size_bytes   = Column(Integer, nullable=True) # surfaced to user as the "disk cost" of exporting
    gguf_quantization      = Column(String, nullable=True) # e.g. "Q4_K_M" — user-chosen quant level
    ollama_model_tag        = Column(String, nullable=True) # e.g. "obsidian-ft-run42:latest"

    # --- Auto-registration result ---
    created_provider_id   = Column(Integer, ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True)
    created_agent_id       = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    auto_register_provider = Column(Boolean, nullable=True, default=True)  # whether a trained model auto-registers as a provider
    auto_register_agent    = Column(Boolean, nullable=True, default=True)  # whether a new Agent is auto-created pointing at it

    error                = Column(Text, nullable=True)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    started_training_at  = Column(DateTime(timezone=True), nullable=True)  # for actual-cost computation on runpod
    completed_at         = Column(DateTime(timezone=True), nullable=True)


class AppSetting(Base):
    """Global platform settings stored as key/value pairs.

    Keys are unique strings (e.g. 'optimizer_provider_id').
    Values are text — callers must cast as needed.
    """
    __tablename__ = "app_settings"

    id         = Column(Integer, primary_key=True, index=True)
    key        = Column(String, unique=True, index=True, nullable=False)
    value      = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WhatsAppChannel(Base):
    """A WhatsApp account linked to an agent via the WhatsApp Web multi-device protocol."""
    __tablename__ = "whatsapp_channels"

    id               = Column(Integer, primary_key=True, index=True)
    user_id          = Column(Integer, ForeignKey("users.id"), nullable=False)
    agent_id         = Column(Integer, ForeignKey("agents.id"), nullable=False)
    name             = Column(String, nullable=False)                         # friendly label
    wa_phone         = Column(String, nullable=True)                          # bound phone number (after auth)
    status           = Column(String, default="disconnected", nullable=False) # pending_qr | connected | disconnected
    allowed_jids     = Column(Text, nullable=True)                            # JSON array of allowed WA JIDs, NULL = allow all
    reject_message   = Column(Text, nullable=True)                            # auto-reply to blocked senders, NULL = silent
    auth_state_path  = Column(String, nullable=True)                          # path to Baileys auth dir
    # Voice reply settings
    voice_reply_enabled    = Column(Boolean, default=False, nullable=False)
    voice_reply_jids       = Column(Text, nullable=True)                      # JSON array of JIDs; NULL = all contacts
    voice_reply_voice      = Column(String, nullable=True)                    # Qwen preset or pocket voice name
    tts_backend            = Column(String, nullable=True)                    # "auto" | "qwen" | "classic"
    voice_clone_audio_path = Column(String, nullable=True)                    # path to stored reference .wav
    voice_clone_ref_text   = Column(Text, nullable=True)                      # transcript of reference audio
    is_active        = Column(Boolean, default=True, nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now())


class WAContactSession(Base):
    """Maps a WhatsApp chat (JID) to a persistent Obsidian AI session."""
    __tablename__ = "wa_contact_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("whatsapp_channels.id"), nullable=False)
    wa_chat_id = Column(String, nullable=False)   # JID e.g. "15551234567@s.whatsapp.net" or "groupid@g.us"
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
