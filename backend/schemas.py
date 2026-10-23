from pydantic import BaseModel, EmailStr
from typing import Optional, Union
from datetime import datetime


# ============================================================================
# Auth Schemas
# ============================================================================

class EncryptedRequest(BaseModel):
    encrypted: str

class UserCreate(BaseModel):
    username    : str
    email       : EmailStr
    password    : str
    role        : str

class UserLogin(BaseModel):
    username    : str
    password    : str

class UserResponse(BaseModel):
    id          : str
    username    : str
    email       : str
    role        : str

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse

class APIClientCreate(BaseModel):
    name: str
    agent_id: Optional[str] = None  # when set, scopes this key to one agent

class APIClientResponse(BaseModel):
    id: str
    name: str
    client_id: str
    agent_id: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class APIClientCreateResponse(BaseModel):
    """Response when creating a new API client - includes the secret (shown only once)."""
    id: str
    name: str
    client_id: str
    agent_id: Optional[str] = None
    client_secret: str  # Only shown once at creation
    is_active: bool
    created_at: datetime
    message: str = "Store the client_secret securely. It will not be shown again."

class APIClientListResponse(BaseModel):
    clients: list[APIClientResponse]

class UserDetailsResponse(BaseModel):
    id: str
    username: str
    email: str
    role: Optional[str] = None
    auth_type: str
    client_name: Optional[str] = None
    permissions: Optional[dict] = None


class ToggleRoleResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse
    message: str


class TOTPSetupResponse(BaseModel):
    qr_code_data_uri: str
    manual_key: str
    message: str = "Scan the QR code with your authenticator app, then verify with a code"


class TOTPStatusResponse(BaseModel):
    totp_enabled: bool


# ============================================================================
# LLM Provider Schemas
# ============================================================================

class LLMProviderCreate(BaseModel):
    name: str
    provider_type: str         # openai | anthropic | google | ollama | openrouter | custom
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    secret_id: Optional[str] = None   # Use a saved secret instead of api_key
    model_id: Optional[str] = None   # Deprecated: model is now set on the agent
    config: Optional[dict] = None

class LLMProviderUpdate(BaseModel):
    name: Optional[str] = None
    provider_type: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    secret_id: Optional[str] = None
    model_id: Optional[str] = None
    config: Optional[dict] = None

class LLMProviderResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: Optional[str] = None
    model_id: Optional[str] = None
    is_active: bool
    config: Optional[dict] = None
    secret_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class LLMProviderListResponse(BaseModel):
    providers: list[LLMProviderResponse]


# ============================================================================
# Agent Schemas
# ============================================================================

class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_vault_id: Optional[str] = None
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp_server_ids: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    vault_file_ids: Optional[list[str]] = None
    skill_ids: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: bool = False
    memory_enabled: bool = True
    sandbox_enabled: bool = False
    config: Optional[dict] = None

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_vault_id: Optional[str] = None
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp_server_ids: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    vault_file_ids: Optional[list[str]] = None
    skill_ids: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: Optional[bool] = None
    memory_enabled: Optional[bool] = None
    sandbox_enabled: Optional[bool] = None
    config: Optional[dict] = None

class AgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_vault_id: Optional[str] = None
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp_server_ids: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    vault_file_ids: Optional[list[str]] = None
    skill_ids: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: bool = False
    memory_enabled: bool = True
    sandbox_enabled: bool = False
    sandbox_container_id: Optional[str] = None
    sandbox_host_port: Optional[int] = None
    config: Optional[dict] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class AgentListResponse(BaseModel):
    agents: list[AgentResponse]

class AgentExportData(BaseModel):
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model_id: Optional[str] = None
    provider_model_id: Optional[str] = None   # kept for backward-compat: used to match provider on import
    tools: Optional[list[str]] = None
    mcp_servers: Optional[list[str]] = None
    knowledge_bases: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: bool = False
    config: Optional[dict] = None

class AgentExportEnvelope(BaseModel):
    aios_export_version: str = "1"
    exported_at: str
    agent: AgentExportData

class AgentImportResponse(BaseModel):
    agent: AgentResponse
    warnings: list[str]


# ============================================================================
# Agent Version Schemas
# ============================================================================

class AgentVersionResponse(BaseModel):
    id: Union[int, str]
    agent_id: Union[int, str]
    version_number: int
    config_snapshot: dict
    change_summary: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class AgentVersionListResponse(BaseModel):
    versions: list[AgentVersionResponse]
    total: int


# ============================================================================
# Provider Import / Export Schemas
# ============================================================================

class ProviderExportData(BaseModel):
    name: str
    provider_type: str
    base_url: Optional[str] = None
    model_id: Optional[str] = None
    config: Optional[dict] = None

class ProviderExportEnvelope(BaseModel):
    aios_export_version: str = "1"
    exported_at: str
    provider: ProviderExportData

class ProviderBulkExportEnvelope(BaseModel):
    aios_export_version: str = "1"
    exported_at: str
    providers: list[ProviderExportData]

class ProviderImportResult(BaseModel):
    provider: LLMProviderResponse
    warnings: list[str]

class ProviderBulkImportResult(BaseModel):
    providers: list[LLMProviderResponse]
    warnings: list[str]


# ============================================================================
# Team Schemas
# ============================================================================

class TeamMemberCreate(BaseModel):
    agent_id: str
    position: int
    override_name: Optional[str] = None
    override_system_prompt: Optional[str] = None
    override_tool_ids: Optional[list[str]] = None
    override_mcp_server_ids: Optional[list[str]] = None
    override_skill_ids: Optional[list[str]] = None
    override_knowledge_base_ids: Optional[list[str]] = None
    can_delegate: bool = True

class TeamMemberUpdate(BaseModel):
    position: Optional[int] = None
    override_name: Optional[str] = None
    override_system_prompt: Optional[str] = None
    override_tool_ids: Optional[list[str]] = None
    override_mcp_server_ids: Optional[list[str]] = None
    override_skill_ids: Optional[list[str]] = None
    override_knowledge_base_ids: Optional[list[str]] = None
    can_delegate: Optional[bool] = None

class TeamMemberResponse(BaseModel):
    id: str
    agent_id: str
    agent_name: str          # base agent's current name, for display when no override_name
    position: int
    override_name: Optional[str] = None
    override_system_prompt: Optional[str] = None
    override_tool_ids: Optional[list[str]] = None
    override_mcp_server_ids: Optional[list[str]] = None
    override_skill_ids: Optional[list[str]] = None
    override_knowledge_base_ids: Optional[list[str]] = None
    can_delegate: bool = True

class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None
    mode: str = "coordinate"   # coordinate | route | collaborate
    members: list[TeamMemberCreate] = []
    sandbox_enabled: bool = False
    config: Optional[dict] = None

class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    sandbox_enabled: Optional[bool] = None
    config: Optional[dict] = None
    # Member list changes go through POST/PATCH/DELETE /teams/{id}/members/*,
    # not a bulk replace here.

class TeamResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    mode: str
    members: list[TeamMemberResponse]
    sandbox_enabled: bool = False
    sandbox_container_id: Optional[str] = None
    sandbox_host_port: Optional[int] = None
    config: Optional[dict] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class TeamListResponse(BaseModel):
    teams: list[TeamResponse]


# ============================================================================
# Session Schemas
# ============================================================================

class SessionCreate(BaseModel):
    entity_type: str           # agent | team
    entity_id: str
    title: Optional[str] = None

class SessionResponse(BaseModel):
    id: str
    title: Optional[str] = None
    entity_type: str
    entity_id: str
    is_active: bool
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


# ============================================================================
# Message Schemas
# ============================================================================

class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: Optional[str] = None
    agent_id: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    reasoning: Optional[list[dict]] = None
    metadata: Optional[dict] = None
    attachments: Optional[list[dict]] = None
    rating: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class MessageListResponse(BaseModel):
    messages: list[MessageResponse]

class RateMessageRequest(BaseModel):
    rating: Optional[str] = None  # "up" | "down" | None (to clear)


# ============================================================================
# File Attachment Schemas
# ============================================================================

class FileAttachmentInfo(BaseModel):
    """File attachment info sent with a chat message."""
    filename: str
    media_type: str
    file_type: str = "document"  # "image" | "document"
    data: Optional[str] = None   # base64 data URI

class FileAttachmentResponse(BaseModel):
    id: str
    filename: str
    media_type: str
    file_type: str
    file_size: Optional[int] = None
    url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# Chat Schemas
# ============================================================================

class ChatRequest(BaseModel):
    session_id: str
    message: str
    stream: bool = True
    attachments: Optional[list[FileAttachmentInfo]] = None


# ============================================================================
# Public Agent API Schemas
# ============================================================================

class PublicAgentChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None  # omit to start a new conversation
    stream: bool = False


class PublicAgentChatResponse(BaseModel):
    conversation_id: str
    message: str
    tool_calls: list[dict] = []


# ============================================================================
# Workflow Schemas
# ============================================================================

class WorkflowStep(BaseModel):
    id: Optional[str] = None           # stable UUID per node; None for legacy linear steps
    node_type: Optional[str] = "agent" # "start" | "agent" | "end" | "condition" | "approval" | "map"
    agent_id: Optional[str] = None     # required for agent nodes; None for start/end nodes
    task: str
    order: int                         # kept for backward compat with legacy linear workflows
    depends_on: Optional[list[str]] = None  # list of step IDs this node depends on; empty = root node
    input_branch: Optional[str] = None # Phase 2: which branch label from a condition node
    position: Optional[dict] = None    # {x, y} canvas position for the visual editor
    config: Optional[dict] = None

class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    steps: list[WorkflowStep]
    config: Optional[dict] = None

class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[list[WorkflowStep]] = None
    config: Optional[dict] = None

class WorkflowResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    steps: list[WorkflowStep]
    config: Optional[dict] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowResponse]


# ============================================================================
# n8n Import Schemas
# ============================================================================

class N8nImportRequest(BaseModel):
    workflow: dict                          # raw n8n export JSON (or a canvas copy-paste)
    name: Optional[str] = None              # override the imported workflow's name
    default_agent_id: Optional[str] = None  # assigned to every agent/map step the import creates
    dry_run: bool = False                   # convert and report only; persist nothing

class N8nImportWarning(BaseModel):
    level: str                              # "info" | "warning"
    code: str
    message: str
    node: Optional[str] = None              # original n8n node name

class N8nImportResponse(BaseModel):
    workflow: Optional[WorkflowResponse] = None  # None on a dry run
    steps: list[WorkflowStep]               # the converted steps, dry run or not
    name: str
    description: Optional[str] = None
    warnings: list[N8nImportWarning]
    schedules: list[dict]                   # cron expressions found on triggers; never auto-created
    needs_agent: list[str]                  # step ids still missing an agent


# ============================================================================
# Workflow Run Schemas
# ============================================================================

class WorkflowRunRequest(BaseModel):
    input: str

class WorkflowStepResult(BaseModel):
    node_id: Optional[str] = None      # DAG node ID; None for legacy runs
    order: int                         # kept for backward compat
    node_type: Optional[str] = "agent" # "start" | "agent" | "end" | "condition" | "approval" | "map" | "map"
    agent_id: Optional[str] = None     # None for non-agent nodes
    agent_name: str
    task: str
    status: str = "pending"            # pending | running | completed | failed | skipped | paused
    output: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    attempts: Optional[int] = None     # how many tries this node took (retry_config)

class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    session_id: Optional[str] = None
    status: str
    current_step: int
    running_nodes: Optional[list[str]] = None  # node IDs currently in-flight (DAG runs)
    steps: list[WorkflowStepResult]
    input_text: Optional[str] = None
    final_output: Optional[str] = None
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class WorkflowRunListResponse(BaseModel):
    runs: list[WorkflowRunResponse]


# ============================================================================
# Dashboard Schemas
# ============================================================================

class DashboardSummary(BaseModel):
    agents_count: int
    teams_count: int
    workflows_count: int
    sessions_count: int


# ============================================================================
# Tool Schemas
# ============================================================================

class ToolDefinitionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    parameters: dict                    # JSON Schema
    handler_type: str = "http"          # http | python | builtin
    handler_config: Optional[dict] = None
    requires_confirmation: bool = False

class ToolDefinitionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    handler_type: Optional[str] = None
    handler_config: Optional[dict] = None
    requires_confirmation: Optional[bool] = None

class ToolDefinitionResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parameters: dict
    handler_type: str
    handler_config: Optional[dict] = None
    requires_confirmation: bool = False
    is_active: bool
    is_model_created: bool = False
    created_at: datetime

    class Config:
        from_attributes = True

class ToolDefinitionListResponse(BaseModel):
    tools: list[ToolDefinitionResponse]


# ============================================================================
# MCP Server Schemas
# ============================================================================

class MCPServerCreate(BaseModel):
    name: str
    description: Optional[str] = None
    transport_type: str                         # stdio | sse
    command: Optional[str] = None               # stdio only
    args: Optional[list[str]] = None            # stdio only
    env: Optional[dict[str, str]] = None        # stdio only
    url: Optional[str] = None                   # sse only
    headers: Optional[dict[str, str]] = None    # sse only

class MCPServerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    transport_type: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None

class MCPServerResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    transport_type: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class MCPServerListResponse(BaseModel):
    mcp_servers: list[MCPServerResponse]


# ============================================================================
# User Secrets Schemas
# ============================================================================

class SecretCreate(BaseModel):
    name: str
    value: str
    description: Optional[str] = None

class SecretUpdate(BaseModel):
    name: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None

class SecretResponse(BaseModel):
    id: str
    name: str
    secret_type: str = "generic"
    fields: dict[str, str] = {}   # field -> masked or clear value, per secret_types.SECRET_TYPE_SCHEMAS
    masked_value: str             # kept for backward compatibility with older frontend builds
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SecretListResponse(BaseModel):
    secrets: list[SecretResponse]

class SecretAccessResponse(BaseModel):
    agent_ids: list[str]

class SecretAccessRequest(BaseModel):
    agent_ids: list[str]

class SecretRevealResponse(BaseModel):
    fields: dict[str, str]   # every field, real decrypted values — only ever returned on explicit reveal


# ============================================================================
# Admin / Permission Schemas
# ============================================================================

class UserPermissions(BaseModel):
    create_agents: bool = True
    create_teams: bool = True
    create_workflows: bool = True
    create_tools: bool = True
    manage_providers: bool = True
    manage_mcp_servers: bool = True
    create_knowledge_bases: bool = True


class AdminUserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    permissions: UserPermissions
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AdminUserListResponse(BaseModel):
    users: list[AdminUserResponse]


class AdminUserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "user"
    permissions: Optional[UserPermissions] = None


class AdminUserUpdate(BaseModel):
    role: Optional[str] = None
    permissions: Optional[UserPermissions] = None


# ============================================================================
# Knowledge Base Schemas
# ============================================================================

class KnowledgeBaseCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_shared: bool = False

class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_shared: Optional[bool] = None

class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_shared: bool
    is_active: bool
    document_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True

class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseResponse]

class KBDocumentCreate(BaseModel):
    doc_type: str                          # "text" | "file"
    name: str
    content_text: Optional[str] = None    # for text type
    file_data: Optional[str] = None       # base64 data URI for file type
    filename: Optional[str] = None
    media_type: Optional[str] = None

class KBDocumentResponse(BaseModel):
    id: str
    kb_id: str
    doc_type: str
    name: str
    filename: Optional[str] = None
    media_type: Optional[str] = None
    indexed: bool
    created_at: datetime

    class Config:
        from_attributes = True

class KBDocumentListResponse(BaseModel):
    documents: list[KBDocumentResponse]


# ============================================================================
# Workflow Schedule Schemas
# ============================================================================

class WorkflowScheduleCreate(BaseModel):
    name: str
    cron_expr: str
    input_text: Optional[str] = None
    is_active: bool = True

class WorkflowScheduleUpdate(BaseModel):
    name: Optional[str] = None
    cron_expr: Optional[str] = None
    input_text: Optional[str] = None
    is_active: Optional[bool] = None

class WorkflowScheduleResponse(BaseModel):
    id: str
    workflow_id: str
    user_id: str
    name: str
    cron_expr: str
    input_text: Optional[str] = None
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class WorkflowScheduleListResponse(BaseModel):
    schedules: list[WorkflowScheduleResponse]


# ============================================================================
# HITL Schemas
# ============================================================================

class HITLApprovalResponse(BaseModel):
    approval_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    tool_arguments: Optional[dict] = None

class HITLPendingListResponse(BaseModel):
    approvals: list[HITLApprovalResponse]


# ============================================================================
# Agent Thread Message Schemas (open multi-agent delegation threads)
# ============================================================================

class AgentThreadMessageResponse(BaseModel):
    id: str
    session_id: str
    thread_id: str
    hop_index: int
    from_agent_id: str
    from_agent_name: Optional[str] = None
    to_agent_id: str
    to_agent_name: Optional[str] = None
    content: Optional[str] = None
    created_at: datetime

class AgentThreadMessageListResponse(BaseModel):
    messages: list[AgentThreadMessageResponse]


# ============================================================================
# Async Job Schemas
# ============================================================================

class AsyncJobResponse(BaseModel):
    job_id: str
    session_id: str
    description: str
    status: str  # pending | completed | failed
    poll_count: int
    last_result: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    resolved_at: Optional[str] = None

class AsyncJobPendingListResponse(BaseModel):
    jobs: list[AsyncJobResponse]


# ============================================================================
# Agent Memory Schemas
# ============================================================================

class AgentMemoryResponse(BaseModel):
    id: str
    agent_id: str
    user_id: str
    key: str
    value: str
    category: str   # preference | context | decision | correction
    confidence: float
    session_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AgentMemoryListResponse(BaseModel):
    memories: list[AgentMemoryResponse]

class AgentMemoryUpdate(BaseModel):
    value: Optional[str] = None
    category: Optional[str] = None
    confidence: Optional[float] = None

class AgentMemoryImportResponse(BaseModel):
    created: int
    updated: int


# ============================================================================
# Trace Schemas
# ============================================================================

class TraceSpanResponse(BaseModel):
    id: str
    session_id: Optional[str] = None
    workflow_run_id: Optional[str] = None
    message_id: Optional[str] = None
    span_type: str          # llm_call | tool_call | mcp_call | workflow_step
    name: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: Optional[float] = None
    duration_ms: int = 0
    status: str             # success | error
    stop_reason: Optional[str] = None
    input_data: Optional[str] = None    # raw JSON string, parsed lazily on frontend
    output_data: Optional[str] = None   # raw JSON string, parsed lazily on frontend
    sequence: int = 0
    round_number: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class SessionTraceResponse(BaseModel):
    session_id: str
    total_duration_ms: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float = 0.0
    span_count: int
    spans: list[TraceSpanResponse]


class WorkflowRunTraceResponse(BaseModel):
    workflow_run_id: str
    total_duration_ms: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float = 0.0
    span_count: int
    spans: list[TraceSpanResponse]


# ============================================================================
# Tool Proposal Schemas
# ============================================================================

class ToolProposalResponse(BaseModel):
    proposal_id: str
    session_id: str
    tool_call_id: str
    name: str
    description: Optional[str] = None
    handler_type: str                       # python | http
    parameters: dict
    handler_config: Optional[dict] = None
    status: str                             # pending | approved | rejected
    created_tool_id: Optional[str] = None  # set after approval (create proposals)
    proposal_type: str = "create"           # create | edit
    target_tool_id: Optional[str] = None   # for edit proposals: existing tool being updated
    # snapshot of the existing tool before the edit (for diff display in the UI)
    existing_description: Optional[str] = None
    existing_parameters: Optional[dict] = None
    existing_handler_config: Optional[dict] = None

class ToolProposalPendingListResponse(BaseModel):
    proposals: list[ToolProposalResponse]


# ============================================================================
# Analytics Schemas
# ============================================================================

class TokenBucket(BaseModel):
    date: str           # ISO date string YYYY-MM-DD
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: float
    call_count: int

class LatencyBucket(BaseModel):
    model: str
    p50_ms: int
    p95_ms: int
    avg_ms: int
    call_count: int

class ToolStat(BaseModel):
    name: str
    call_count: int
    error_count: int
    avg_duration_ms: int
    error_rate: float

class CostByAgent(BaseModel):
    agent_id: Optional[str]
    agent_name: Optional[str]
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    session_count: int

class AnalyticsOverview(BaseModel):
    total_sessions: int
    total_llm_calls: int
    total_tool_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    avg_latency_ms: int
    error_rate: float

class TokensOverTimeResponse(BaseModel):
    buckets: list[TokenBucket]
    range_days: int

class LatencyByModelResponse(BaseModel):
    models: list[LatencyBucket]

class ToolStatsResponse(BaseModel):
    tools: list[ToolStat]

class CostByAgentResponse(BaseModel):
    agents: list[CostByAgent]

class AnalyticsOverviewResponse(BaseModel):
    overview: AnalyticsOverview


# ============================================================================
# Eval Harness Schemas
# ============================================================================

class EvalTestCase(BaseModel):
    id: str                             # uuid, stable reference for result matching
    input: str
    expected_output: str
    grading_method: str                 # exact_match | contains | llm_judge
    weight: float = 1.0

class EvalSuiteCreate(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: Optional[Union[int, str]] = None
    judge_agent_id: Optional[Union[int, str]] = None  # agent used for llm_judge grading
    test_cases: list[EvalTestCase] = []

class EvalSuiteUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[Union[int, str]] = None
    judge_agent_id: Optional[Union[int, str]] = None
    test_cases: Optional[list[EvalTestCase]] = None

class EvalSuiteResponse(BaseModel):
    id: Union[int, str]
    user_id: Union[int, str]
    agent_id: Optional[Union[int, str]] = None
    judge_agent_id: Optional[Union[int, str]] = None
    name: str
    description: Optional[str] = None
    test_cases: list[EvalTestCase]
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class EvalSuiteListResponse(BaseModel):
    suites: list[EvalSuiteResponse]

class EvalCaseResult(BaseModel):
    case_id: str
    input: str
    expected: str
    actual_output: str
    passed: bool
    score: float                        # 0.0 or 1.0 for exact/contains; 0.0–1.0 for llm_judge
    reasoning: Optional[str] = None    # only for llm_judge

class EvalRunResponse(BaseModel):
    id: Union[int, str]
    suite_id: Union[int, str]
    agent_id: Optional[Union[int, str]] = None
    version_id: Optional[Union[int, str]] = None
    status: str                         # pending | running | completed | failed
    results: Optional[list[EvalCaseResult]] = None
    score: Optional[float] = None
    total_cases: int
    passed_cases: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class EvalRunListResponse(BaseModel):
    runs: list[EvalRunResponse]

class RunEvalRequest(BaseModel):
    agent_id: Union[int, str]
    version_id: Optional[Union[int, str]] = None   # if set, runs against that snapshot
    override_system_prompt: Optional[str] = None   # for optimizer validation


# ─── Prompt Auto-Optimizer ────────────────────────────────────────────────────

class FailurePattern(BaseModel):
    pattern: str
    description: str
    frequency: int
    severity: str                       # low | medium | high
    example_trace_ids: list[str] = []

class OptimizationRunResponse(BaseModel):
    id: Union[int, str]
    agent_id: Union[int, str]
    user_id: Union[int, str]
    status: str                         # pending | analyzing | proposing | validating | awaiting_review | accepted | rejected | failed
    trace_count: int
    failure_patterns: Optional[list[FailurePattern]] = None
    current_prompt: Optional[str] = None
    proposed_prompt: Optional[str] = None
    rationale: Optional[str] = None
    eval_suite_id: Optional[Union[int, str]] = None
    eval_run_id: Optional[Union[int, str]] = None
    baseline_score: Optional[float] = None
    proposed_score: Optional[float] = None
    accepted_version_id: Optional[Union[int, str]] = None
    rejected_reason: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class OptimizationRunListResponse(BaseModel):
    runs: list[OptimizationRunResponse]

class TriggerOptimizationRequest(BaseModel):
    agent_id: Union[int, str]
    eval_suite_id: Optional[Union[int, str]] = None   # if set, runs eval to validate the proposal
    audit_run_id: Optional[Union[int, str]] = None    # if set, feeds audit findings as extra failure-signal context
    inspection_run_id: Optional[Union[int, str]] = None   # if set, feeds inspection findings as extra failure-signal context (projections/attention only — never belief/intent claims, see optimizer.py's _build_inspection_context_text)
    min_traces: int = 5
    max_traces: int = 50

class RejectOptimizationRequest(BaseModel):
    reason: Optional[str] = None


# ============================================================================
# Behavioral Consistency Auditor Schemas
# ============================================================================
# Phase 1 of model auditing: black-box probe testing (paraphrase/order/
# adversarial/repeat/CoT-alignment consistency), not interpretability.
# See backend/auditor_engine.py.

class AuditProbeResult(BaseModel):
    category: str                        # paraphrase | order | adversarial | repeat | cot_alignment
    original_prompt: str
    variant_prompt: str
    original_response: str
    variant_response: str
    consistency_score: float             # 0.0–1.0, from the judge LLM
    passed: bool
    disagreement_type: Optional[str] = None   # none | conclusion | action | tone_only
    reasoning: Optional[str] = None
    cot_text: Optional[str] = None            # only for cot_alignment probes
    cot_alignment_flag: Optional[bool] = None # only for cot_alignment probes

class AuditRunResponse(BaseModel):
    id: Union[int, str]
    agent_id: Union[int, str]
    user_id: Union[int, str]
    status: str                          # pending | generating_probes | running_probes | scoring | completed | failed
    seed_prompt: str
    probe_categories: list[str]
    probes_per_category: int
    judge_agent_id: Optional[Union[int, str]] = None
    results: Optional[list[AuditProbeResult]] = None
    score: Optional[float] = None
    category_scores: Optional[dict[str, float]] = None
    triggered_optimization_run_id: Optional[Union[int, str]] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class AuditRunListResponse(BaseModel):
    runs: list[AuditRunResponse]

class TriggerAuditRequest(BaseModel):
    agent_id: Union[int, str]
    seed_prompt: str
    probe_categories: list[str] = ["paraphrase", "order", "adversarial", "repeat", "cot_alignment"]
    probes_per_category: int = 5
    judge_agent_id: Optional[Union[int, str]] = None


# ============================================================================
# Local Model Inspection Schemas (phase 2 of model auditing)
# ============================================================================
# Real activation/attention/logit-lens inspection of a LOCAL model's real HF
# weights, via the separate inspector_service — not interpretability, not
# available for cloud-provider agents (their weights are never reachable).
# See backend/inspector_engine.py and models.py's InspectionRun docstring.

class InspectionLayerSummary(BaseModel):
    layer: int
    residual_norm: Optional[float] = None
    logit_lens_top_tokens: Optional[list[dict]] = None   # [{token, probability}]
    attention_entropy_by_head: Optional[list[float]] = None
    num_heads: Optional[int] = None

class InspectionSummary(BaseModel):
    token_count: int
    truncated: bool
    per_layer: list[InspectionLayerSummary]

class InspectionCaptureConfig(BaseModel):
    layers: Optional[list[int]] = None   # None = all layers, summary stats only (no full-resolution tensors)
    capture_attention: bool = True
    capture_residual: bool = True
    logit_lens_topk: int = 5
    max_seq_len: int = 256

class InspectionRunResponse(BaseModel):
    id: Union[int, str]
    agent_id: Union[int, str]
    user_id: Union[int, str]
    status: str   # pending | loading_model | capturing | processing | completed | failed | cancelled
    prompt: str
    hf_model_id: str
    capture_config: Optional[InspectionCaptureConfig] = None
    summary: Optional[InspectionSummary] = None
    has_artifact: bool = False
    triggered_optimization_run_id: Optional[Union[int, str]] = None
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class InspectionRunListResponse(BaseModel):
    runs: list[InspectionRunResponse]

class TriggerInspectionRequest(BaseModel):
    agent_id: Union[int, str]
    hf_model_id: str
    prompt: str
    capture_config: InspectionCaptureConfig = InspectionCaptureConfig()

class InspectorStatusResponse(BaseModel):
    reachable: bool
    model_loaded: Optional[str] = None


# ============================================================================
# LoRA Fine-Tuning Schemas
# ============================================================================

class FineTuneHyperparams(BaseModel):
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: list[str] = ["q_proj", "v_proj"]
    learning_rate: float = 2e-4
    num_epochs: int = 3
    per_device_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    max_seq_len: int = 1024
    quantization: str = "4bit"   # "4bit" | "8bit" | "none"
    seed: int = 42

class FineTuneDatasetSource(BaseModel):
    type: str   # "session_export" | "uploaded_file"
    session_ids: Optional[list[Union[int, str]]] = None
    file_data: Optional[str] = None   # base64 data-URI, if uploaded_file
    filename: Optional[str] = None

class TriggerFineTuneRequest(BaseModel):
    agent_id: Union[int, str]
    base_hf_model_id: str
    compute_backend: str   # "runpod" | "local_wsl2"
    dataset: FineTuneDatasetSource
    hyperparams: FineTuneHyperparams = FineTuneHyperparams()
    export_to_ollama: bool = False
    gguf_quantization: Optional[str] = "Q4_K_M"
    auto_register_provider: bool = True
    auto_register_agent: bool = True

class FineTuneProgress(BaseModel):
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    current_epoch: Optional[int] = None
    total_epochs: Optional[int] = None
    loss: Optional[float] = None
    eta_seconds: Optional[int] = None

class FineTuneRunResponse(BaseModel):
    id: Union[int, str]
    agent_id: Union[int, str]
    user_id: Union[int, str]
    compute_backend: str
    status: str
    base_hf_model_id: str
    dataset_source_type: str
    dataset_row_count: Optional[int] = None
    dataset_filename: Optional[str] = None
    hyperparams: Optional[FineTuneHyperparams] = None
    runpod_estimated_cost_usd: Optional[float] = None
    runpod_actual_cost_usd: Optional[float] = None
    progress: Optional[FineTuneProgress] = None
    adapter_size_bytes: Optional[int] = None
    export_to_ollama: bool = False
    merged_gguf_size_bytes: Optional[int] = None
    gguf_quantization: Optional[str] = None
    ollama_model_tag: Optional[str] = None
    created_provider_id: Optional[Union[int, str]] = None
    created_agent_id: Optional[Union[int, str]] = None
    error: Optional[str] = None
    created_at: datetime
    started_training_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class FineTuneRunListResponse(BaseModel):
    runs: list[FineTuneRunResponse]

class FineTuneCostEstimateResponse(BaseModel):
    estimated_usd: Optional[float] = None   # null for local_wsl2
    estimated_minutes: float
    disk_cost_gb: Optional[float] = None     # only meaningful if export_to_ollama
    caveat: str


# ============================================================================
# Prompt Vault Schemas
# ============================================================================

class PromptVaultCreate(BaseModel):
    name: str
    description: Optional[str] = None
    content: str

class PromptVaultUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None

class PromptVaultResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class PromptVaultListResponse(BaseModel):
    prompts: list[PromptVaultResponse]


# ─── Markdown Vault (file manager) ──────────────────────────────────────────

class VaultFileCreate(BaseModel):
    name: str
    folder: Optional[str] = None
    content: str = ""

class VaultFileUpdate(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None
    content: Optional[str] = None

class VaultFileResponse(BaseModel):
    id: str
    name: str
    folder: Optional[str] = None
    content: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class VaultFileListResponse(BaseModel):
    files: list[VaultFileResponse]

class VaultFileUseAsKBRequest(BaseModel):
    kb_id: str


# ─── Skills Vault ──────────────────────────────────────────────────────────

class SkillCreate(BaseModel):
    name: str
    description: Optional[str] = None
    instructions: str

class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None

class SkillResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    instructions: str
    file_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SkillListResponse(BaseModel):
    skills: list[SkillResponse]

class SkillFileCreate(BaseModel):
    filename: str
    file_data: str   # base64 data URI

class SkillFileResponse(BaseModel):
    id: str
    skill_id: str
    filename: str
    media_type: str
    file_size: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SkillFileListResponse(BaseModel):
    files: list[SkillFileResponse]


# ─── Optimizer Vault Actions ──────────────────────────────────────────────────

class OptimizerSaveToVaultRequest(BaseModel):
    name: str
    description: Optional[str] = None

class OptimizerUpdateVaultRequest(BaseModel):
    vault_id: str
