from pydantic import BaseModel, EmailStr
from typing import Optional
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

class APIClientResponse(BaseModel):
    id: str
    name: str
    client_id: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

class APIClientCreateResponse(BaseModel):
    """Response when creating a new API client - includes the secret (shown only once)."""
    id: str
    name: str
    client_id: str
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
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp_server_ids: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: bool = False
    config: Optional[dict] = None

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp_server_ids: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: Optional[bool] = None
    config: Optional[dict] = None

class AgentResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    tools: Optional[list[str]] = None
    mcp_server_ids: Optional[list[str]] = None
    knowledge_base_ids: Optional[list[str]] = None
    hitl_confirmation_tools: Optional[list[str]] = None
    allow_tool_creation: bool = False
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

class TeamCreate(BaseModel):
    name: str
    description: Optional[str] = None
    mode: str = "coordinate"   # coordinate | route | collaborate
    agent_ids: list[str]
    config: Optional[dict] = None

class TeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    agent_ids: Optional[list[str]] = None
    config: Optional[dict] = None

class TeamResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    mode: str
    agent_ids: list[str]
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
# Workflow Schemas
# ============================================================================

class WorkflowStep(BaseModel):
    id: Optional[str] = None           # stable UUID per node; None for legacy linear steps
    node_type: Optional[str] = "agent" # "start" | "agent" | "end" | "condition" | "approval"
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
# Workflow Run Schemas
# ============================================================================

class WorkflowRunRequest(BaseModel):
    input: str

class WorkflowStepResult(BaseModel):
    node_id: Optional[str] = None      # DAG node ID; None for legacy runs
    order: int                         # kept for backward compat
    node_type: Optional[str] = "agent" # "start" | "agent" | "end"
    agent_id: Optional[str] = None     # None for non-agent nodes
    agent_name: str
    task: str
    status: str = "pending"            # pending | running | completed | failed
    output: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

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
    masked_value: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class SecretListResponse(BaseModel):
    secrets: list[SecretResponse]


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
    duration_ms: int = 0
    status: str             # success | error
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
    span_count: int
    spans: list[TraceSpanResponse]


class WorkflowRunTraceResponse(BaseModel):
    workflow_run_id: str
    total_duration_ms: int
    total_input_tokens: int
    total_output_tokens: int
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
    created_tool_id: Optional[str] = None  # set after approval

class ToolProposalPendingListResponse(BaseModel):
    proposals: list[ToolProposalResponse]
