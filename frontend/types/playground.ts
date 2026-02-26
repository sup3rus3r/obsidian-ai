export interface LLMProvider {
  id: string
  name: string
  provider_type: "openai" | "anthropic" | "google" | "ollama" | "openrouter" | "custom"
  base_url?: string
  model_id: string
  is_active: boolean
  config?: Record<string, unknown>
  secret_id?: string
  created_at: string
}

export interface Agent {
  id: string
  name: string
  description?: string
  system_prompt?: string
  provider_id?: string
  tools?: string[]
  mcp_server_ids?: string[]
  knowledge_base_ids?: string[]
  hitl_confirmation_tools?: string[]
  allow_tool_creation?: boolean
  config?: Record<string, unknown>
  is_active: boolean
  created_at: string
}

export interface Team {
  id: string
  name: string
  description?: string
  mode: "coordinate" | "route" | "collaborate"
  agent_ids: string[]
  config?: Record<string, unknown>
  is_active: boolean
  created_at: string
}

export interface Session {
  id: string
  title?: string
  entity_type: "agent" | "team" | "workflow"
  entity_id: string
  is_active: boolean
  total_input_tokens: number
  total_output_tokens: number
  created_at: string
  updated_at?: string
}

export interface ToolCall {
  id: string
  name: string
  arguments: Record<string, unknown> | string
  result?: string
  status: "pending" | "running" | "completed" | "error"
}

export interface ReasoningStep {
  type: "thinking" | "planning" | "reflection"
  content: string
}

export interface AgentStep {
  agent_id: string
  agent_name: string
  step: "routing" | "responding" | "completed" | "synthesizing" | "selected"
}

export interface ToolRound {
  round: number
  max_rounds: number
}

export interface MessageMetadata {
  model?: string
  tokens_used?: { prompt: number; completion: number; total: number }
  input_tokens?: number
  output_tokens?: number
  latency_ms?: number
  provider?: string
  team_mode?: "coordinate" | "route" | "collaborate"
  contributing_agents?: { id: string; name: string }[]
  chain_agents?: { id: string; name: string }[]
}

export interface FileAttachment {
  id?: string
  filename: string
  media_type: string
  file_type: "image" | "document"
  url?: string
  data?: string
}

export interface Message {
  id: string
  session_id: string
  role: "user" | "assistant" | "system" | "tool"
  content?: string
  agent_id?: string
  tool_calls?: ToolCall[]
  reasoning?: ReasoningStep[]
  metadata?: MessageMetadata
  attachments?: FileAttachment[]
  rating?: "up" | "down" | null
  created_at: string
}

export type StreamEvent =
  | { type: "content_delta"; content: string }
  | { type: "tool_call_start"; tool_call: ToolCall }
  | { type: "tool_call_result"; tool_call_id: string; result: string }
  | { type: "reasoning_delta"; reasoning: ReasoningStep }
  | { type: "agent_step"; agent_id: string; agent_name: string; step: string }
  | { type: "message_complete"; message: Message }
  | { type: "error"; error: string }
  | { type: "done" }

export interface Secret {
  id: string
  name: string
  masked_value: string
  description?: string
  created_at: string
  updated_at?: string
}

export interface CreateProviderRequest {
  name: string
  provider_type: string
  base_url?: string
  api_key?: string
  secret_id?: string
  model_id: string
  config?: Record<string, unknown>
}

export interface CreateAgentRequest {
  name: string
  description?: string
  system_prompt?: string
  provider_id?: string
  tools?: string[]
  mcp_server_ids?: string[]
  knowledge_base_ids?: string[]
  hitl_confirmation_tools?: string[]
  allow_tool_creation?: boolean
  config?: Record<string, unknown>
}

export interface UpdateAgentRequest {
  name?: string
  description?: string
  system_prompt?: string
  provider_id?: string
  tools?: string[]
  mcp_server_ids?: string[]
  knowledge_base_ids?: string[]
  hitl_confirmation_tools?: string[]
  allow_tool_creation?: boolean
  config?: Record<string, unknown>
}

// Knowledge Bases
export interface KnowledgeBase {
  id: string
  name: string
  description?: string
  is_shared: boolean
  is_active: boolean
  document_count: number
  created_at: string
}

export interface KBDocument {
  id: string
  kb_id: string
  doc_type: "text" | "file"
  name: string
  filename?: string
  media_type?: string
  indexed: boolean
  created_at: string
}

export interface CreateKnowledgeBaseRequest {
  name: string
  description?: string
  is_shared?: boolean
}

export interface UpdateKnowledgeBaseRequest {
  name?: string
  description?: string
  is_shared?: boolean
}

export interface CreateKBDocumentRequest {
  doc_type: "text" | "file"
  name: string
  content_text?: string
  file_data?: string
  filename?: string
  media_type?: string
}

export interface CreateTeamRequest {
  name: string
  description?: string
  mode?: string
  agent_ids: string[]
  config?: Record<string, unknown>
}

export interface CreateSessionRequest {
  entity_type: "agent" | "team" | "workflow"
  entity_id: string
  title?: string
}

// Workflows
export interface WorkflowStep {
  agent_id: string
  task: string
  order: number
  config?: Record<string, unknown>
}

export interface Workflow {
  id: string
  name: string
  description?: string
  steps: WorkflowStep[]
  config?: Record<string, unknown>
  is_active: boolean
  created_at: string
}

export interface CreateWorkflowRequest {
  name: string
  description?: string
  steps: WorkflowStep[]
  config?: Record<string, unknown>
}

export interface UpdateWorkflowRequest {
  name?: string
  description?: string
  steps?: WorkflowStep[]
  config?: Record<string, unknown>
}

// Workflow Runs
export interface WorkflowStepResult {
  order: number
  agent_id: string
  agent_name: string
  task: string
  status: "pending" | "running" | "completed" | "failed"
  output?: string
  started_at?: string
  completed_at?: string
  error?: string
}

export interface WorkflowRun {
  id: string
  workflow_id: string
  session_id?: string
  status: "running" | "completed" | "failed" | "cancelled"
  current_step: number
  steps: WorkflowStepResult[]
  input_text?: string
  final_output?: string
  error?: string
  started_at: string
  completed_at?: string
}

// Tool Definitions
export interface ToolDefinition {
  id: string
  name: string
  description?: string
  parameters: Record<string, unknown>
  handler_type: "http" | "python" | "builtin"
  handler_config?: Record<string, unknown>
  requires_confirmation?: boolean
  is_active: boolean
  created_at: string
}

export interface CreateToolRequest {
  name: string
  description?: string
  parameters: Record<string, unknown>
  handler_type?: string
  handler_config?: Record<string, unknown>
  requires_confirmation?: boolean
}

export interface UpdateToolRequest {
  name?: string
  description?: string
  parameters?: Record<string, unknown>
  handler_type?: string
  handler_config?: Record<string, unknown>
  requires_confirmation?: boolean
}

// Agent Memory
export interface AgentMemory {
  id: string
  agent_id: string
  user_id: string
  key: string
  value: string
  category: "preference" | "context" | "decision" | "correction"
  confidence: number
  session_id?: string
  created_at: string
  updated_at?: string
}

// HITL
export interface HITLApprovalEvent {
  approval_id: string
  session_id: string
  tool_call_id: string
  tool_name: string
  tool_arguments: Record<string, unknown>
}

// Tool Proposals
export interface ToolProposalEvent {
  proposal_id: string
  session_id: string
  tool_call_id: string
  name: string
  description?: string
  handler_type: "python" | "http"
  parameters: Record<string, unknown>
  handler_config?: Record<string, unknown>
}

// MCP Servers
export interface MCPServer {
  id: string
  name: string
  description?: string
  transport_type: "stdio" | "sse"
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
  is_active: boolean
  created_at: string
}

export interface CreateMCPServerRequest {
  name: string
  description?: string
  transport_type: "stdio" | "sse"
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
}

export interface UpdateMCPServerRequest {
  name?: string
  description?: string
  transport_type?: "stdio" | "sse"
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
}

// Workflow Schedules
export interface WorkflowSchedule {
  id: string
  workflow_id: string
  user_id: string
  name: string
  cron_expr: string
  input_text?: string
  is_active: boolean
  last_run_at?: string
  next_run_at?: string
  created_at: string
}

export interface CreateWorkflowScheduleRequest {
  name: string
  cron_expr: string
  input_text?: string
  is_active?: boolean
}

export interface UpdateWorkflowScheduleRequest {
  name?: string
  cron_expr?: string
  input_text?: string
  is_active?: boolean
}

// Execution Traces
export interface TraceSpan {
  id: string
  session_id?: string
  workflow_run_id?: string
  message_id?: string
  span_type: "llm_call" | "tool_call" | "mcp_call" | "workflow_step"
  name: string
  input_tokens: number
  output_tokens: number
  duration_ms: number
  status: "success" | "error"
  input_data?: string
  output_data?: string
  sequence: number
  round_number: number
  created_at: string
}

export interface SessionTrace {
  session_id: string
  spans: TraceSpan[]
  total_duration_ms: number
  total_input_tokens: number
  total_output_tokens: number
  span_count: number
}

export interface WorkflowRunTrace {
  workflow_run_id: string
  spans: TraceSpan[]
  total_duration_ms: number
  total_input_tokens: number
  total_output_tokens: number
  span_count: number
}

// Artifacts — persistent editable content panels
export type ArtifactType = "html" | "jsx" | "tsx" | "css" | "javascript" | "typescript" | "python" | "markdown" | "text" | "json" | "svg" | "latex"

export interface Artifact {
  id: string
  title: string
  type: ArtifactType
  content: string
  sessionId: string
  createdAt: string
  updatedAt: string
}

export interface ArtifactEvent {
  id: string
  title: string
  type: ArtifactType
  content: string
  is_complete: boolean
}

// AI Elements — rich chat components
export interface FileNode {
  name: string
  path: string
  type: "file" | "directory"
  children?: FileNode[]
}

export interface PlanData {
  title: string
  description?: string
  steps: string[]
  isComplete: boolean
}

// Dashboard
export interface DashboardSummary {
  agents_count: number
  teams_count: number
  workflows_count: number
  sessions_count: number
}

// Admin
export interface UserPermissions {
  create_agents: boolean
  create_teams: boolean
  create_workflows: boolean
  create_tools: boolean
  manage_providers: boolean
  manage_mcp_servers: boolean
  create_knowledge_bases: boolean
}

export const DEFAULT_PERMISSIONS: UserPermissions = {
  create_agents: true,
  create_teams: true,
  create_workflows: true,
  create_tools: true,
  manage_providers: true,
  manage_mcp_servers: true,
  create_knowledge_bases: true,
}

export const PERMISSION_LABELS: Record<keyof UserPermissions, string> = {
  create_agents: "Create Agents",
  create_teams: "Create Teams",
  create_workflows: "Create Workflows",
  create_tools: "Create Tools",
  manage_providers: "Manage Providers",
  manage_mcp_servers: "Manage MCP Servers",
  create_knowledge_bases: "Create Knowledge Bases",
}

export interface AdminUser {
  id: string
  username: string
  email: string
  role: string
  permissions: UserPermissions
  created_at?: string
}

export interface CreateUserRequest {
  username: string
  email: string
  password: string
  role: string
  permissions?: UserPermissions
}

export interface UpdateUserRequest {
  role?: string
  permissions?: UserPermissions
}
