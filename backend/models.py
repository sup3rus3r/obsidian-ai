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
    """API clients for external access with client_id/secret authentication."""
    __tablename__ = "api_clients"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    client_id     = Column(String, unique=True, index=True, nullable=False)
    hashed_secret = Column(String, nullable=False)
    created_by    = Column(Integer, ForeignKey("users.id"), nullable=False)
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
    model_id      = Column(String, nullable=False)
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
    hitl_confirmation_tools_json = Column(Text, nullable=True)  # JSON array of tool names requiring HITL
    allow_tool_creation = Column(Boolean, default=False, nullable=False)  # agent can propose new tools
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
    """A reusable tool/function definition."""
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
    """User-managed secrets (generic key-value pairs, encrypted at rest)."""
    __tablename__ = "user_secrets"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    name            = Column(String, nullable=False)
    encrypted_value = Column(String, nullable=False)
    description     = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())


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
    status              = Column(String, default="pending", nullable=False)  # pending | approved | rejected
    created_tool_id     = Column(Integer, nullable=True)        # ID of the created ToolDefinition if approved
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at         = Column(DateTime(timezone=True), nullable=True)


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

    id              = Column(Integer, primary_key=True, index=True)
    session_id      = Column(Integer, ForeignKey("sessions.id"), nullable=True, index=True)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=True, index=True)
    message_id      = Column(Integer, ForeignKey("messages.id"), nullable=True)
    span_type       = Column(String, nullable=False)               # llm_call | tool_call | mcp_call | workflow_step
    name            = Column(String, nullable=False)               # model name OR tool name
    input_tokens    = Column(Integer, default=0, nullable=False)
    output_tokens   = Column(Integer, default=0, nullable=False)
    duration_ms     = Column(Integer, default=0, nullable=False)
    status          = Column(String, default="success", nullable=False)  # success | error
    input_data      = Column(Text, nullable=True)                  # JSON string (truncated)
    output_data     = Column(Text, nullable=True)                  # JSON string (truncated)
    sequence        = Column(Integer, default=0, nullable=False)   # ordering within a generator invocation
    round_number    = Column(Integer, default=0, nullable=False)   # tool loop round index
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
