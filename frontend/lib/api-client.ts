import { signOut } from "next-auth/react"
import { AppRoutes } from "@/app/api/routes"
import type {
  LLMProvider,
  Agent,
  Team,
  Workflow,
  Session,
  Message,
  ToolDefinition,
  MCPServer,
  CreateProviderRequest,
  CreateAgentRequest,
  UpdateAgentRequest,
  CreateTeamRequest,
  CreateWorkflowRequest,
  UpdateWorkflowRequest,
  WorkflowRun,
  CreateToolRequest,
  UpdateToolRequest,
  CreateMCPServerRequest,
  UpdateMCPServerRequest,
  CreateSessionRequest,
  DashboardSummary,
  AdminUser,
  CreateUserRequest,
  UpdateUserRequest,
  KnowledgeBase,
  KBDocument,
  CreateKnowledgeBaseRequest,
  UpdateKnowledgeBaseRequest,
  CreateKBDocumentRequest,
  WorkflowSchedule,
  CreateWorkflowScheduleRequest,
  UpdateWorkflowScheduleRequest,
  AgentMemory,
  SessionTrace,
  WorkflowRunTrace,
} from "@/types/playground"

interface ApiResponse<T> {
  data?: T
  error?: string
  [key: string]: any
}

interface ListResponse<T> {
  [key: string]: T[]
}

class ApiClient {
  private accessToken: string = ""

  setAccessToken(token: string) {
    this.accessToken = token
  }

  private async request<T>(
    url: string,
    options: RequestInit = {},
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    }

    if (options.headers && typeof options.headers === "object") {
      Object.assign(headers, options.headers)
    }

    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }

    const response = await fetch(url, {
      ...options,
      headers,
    })

    if (!response.ok) {
      if (response.status === 401) {
        signOut({ callbackUrl: "/login" })
        throw new Error("Session expired. Redirecting to login...")
      }
      const error = await response.json().catch(() => ({ detail: "Unknown error" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }

    if (response.status === 204 || response.headers.get("content-length") === "0") {
      return undefined as T
    }
    return response.json()
  }

  // ============= Providers =============
  async listProviders(): Promise<LLMProvider[]> {
    const result = await this.request<ListResponse<LLMProvider>>(AppRoutes.ListProviders())
    return result.providers || []
  }

  async getProvider(id: string): Promise<LLMProvider> {
    return this.request<LLMProvider>(AppRoutes.GetProvider(id))
  }

  async createProvider(data: CreateProviderRequest): Promise<LLMProvider> {
    return this.request<LLMProvider>(AppRoutes.CreateProvider(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateProvider(id: string, data: Partial<CreateProviderRequest>): Promise<LLMProvider> {
    return this.request<LLMProvider>(AppRoutes.UpdateProvider(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteProvider(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteProvider(id), {
      method: "DELETE",
    })
  }

  async testProvider(id: string): Promise<{ success: boolean; message?: string }> {
    return this.request<{ success: boolean; message?: string }>(
      AppRoutes.TestProvider(id),
      { method: "POST" },
    )
  }

  async listModels(providerId: string): Promise<string[]> {
    const result = await this.request<{ models: string[] }>(AppRoutes.ListModels(providerId))
    return result.models || []
  }

  async exportProvider(id: string, name: string): Promise<void> {
    const headers: Record<string, string> = {}
    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }
    const response = await fetch(AppRoutes.ExportProvider(id), { headers })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Export failed" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${name.replace(/[^a-z0-9\-_ ]/gi, "_")}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  async exportAllProviders(): Promise<void> {
    const headers: Record<string, string> = {}
    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }
    const response = await fetch(AppRoutes.ExportAllProviders(), { headers })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Export failed" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = "providers_export.json"
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  async importProvider(file: File): Promise<{ provider: LLMProvider; warnings: string[] }> {
    const headers: Record<string, string> = {}
    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }
    const formData = new FormData()
    formData.append("file", file)
    const response = await fetch(AppRoutes.ImportProvider(), {
      method: "POST",
      headers,
      body: formData,
    })
    if (!response.ok) {
      if (response.status === 401) {
        signOut({ callbackUrl: "/login" })
        throw new Error("Session expired. Redirecting to login...")
      }
      const error = await response.json().catch(() => ({ detail: "Import failed" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }
    return response.json()
  }

  async importProvidersBulk(file: File): Promise<{ providers: LLMProvider[]; warnings: string[] }> {
    const headers: Record<string, string> = {}
    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }
    const formData = new FormData()
    formData.append("file", file)
    const response = await fetch(AppRoutes.ImportProvidersBulk(), {
      method: "POST",
      headers,
      body: formData,
    })
    if (!response.ok) {
      if (response.status === 401) {
        signOut({ callbackUrl: "/login" })
        throw new Error("Session expired. Redirecting to login...")
      }
      const error = await response.json().catch(() => ({ detail: "Import failed" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }
    return response.json()
  }

  // ============= Agents =============
  async listAgents(): Promise<Agent[]> {
    const result = await this.request<ListResponse<Agent>>(AppRoutes.ListAgents())
    return result.agents || []
  }

  async getAgent(id: string): Promise<Agent> {
    return this.request<Agent>(AppRoutes.GetAgent(id))
  }

  async createAgent(data: CreateAgentRequest): Promise<Agent> {
    return this.request<Agent>(AppRoutes.CreateAgent(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateAgent(id: string, data: UpdateAgentRequest): Promise<Agent> {
    return this.request<Agent>(AppRoutes.UpdateAgent(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteAgent(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteAgent(id), {
      method: "DELETE",
    })
  }

  async exportAgent(id: string, agentName: string): Promise<void> {
    const headers: Record<string, string> = {}
    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }
    const response = await fetch(AppRoutes.ExportAgent(id), { headers })
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Export failed" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${agentName.replace(/[^a-z0-9\-_ ]/gi, "_")}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  async importAgent(file: File): Promise<{ agent: Agent; warnings: string[] }> {
    const headers: Record<string, string> = {}
    if (this.accessToken) {
      headers.Authorization = `Bearer ${this.accessToken}`
    }
    const formData = new FormData()
    formData.append("file", file)
    const response = await fetch(AppRoutes.ImportAgent(), {
      method: "POST",
      headers,
      body: formData,
    })
    if (!response.ok) {
      if (response.status === 401) {
        signOut({ callbackUrl: "/login" })
        throw new Error("Session expired. Redirecting to login...")
      }
      const error = await response.json().catch(() => ({ detail: "Import failed" }))
      throw new Error(error.detail || `HTTP ${response.status}`)
    }
    return response.json()
  }

  // ============= Teams =============
  async listTeams(): Promise<Team[]> {
    const result = await this.request<ListResponse<Team>>(AppRoutes.ListTeams())
    return result.teams || []
  }

  async getTeam(id: string): Promise<Team> {
    return this.request<Team>(AppRoutes.GetTeam(id))
  }

  async createTeam(data: CreateTeamRequest): Promise<Team> {
    return this.request<Team>(AppRoutes.CreateTeam(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateTeam(id: string, data: Partial<CreateTeamRequest>): Promise<Team> {
    return this.request<Team>(AppRoutes.UpdateTeam(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteTeam(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteTeam(id), {
      method: "DELETE",
    })
  }

  // ============= Sessions =============
  async listSessions(): Promise<Session[]> {
    const result = await this.request<ListResponse<Session>>(AppRoutes.ListSessions())
    return result.sessions || []
  }

  async getSession(id: string): Promise<Session> {
    return this.request<Session>(AppRoutes.GetSession(id))
  }

  async createSession(data: CreateSessionRequest): Promise<Session> {
    return this.request<Session>(AppRoutes.CreateSession(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async getSessionMessages(id: string): Promise<Message[]> {
    const result = await this.request<ListResponse<Message>>(AppRoutes.GetSessionMessages(id))
    return result.messages || []
  }

  async deleteSession(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteSession(id), {
      method: "DELETE",
    })
  }

  async listSessionsFiltered(entityType?: string, entityId?: string): Promise<Session[]> {
    let url = AppRoutes.ListSessions()
    const params = new URLSearchParams()
    if (entityType) params.set("entity_type", entityType)
    if (entityId) params.set("entity_id", entityId)
    if (params.toString()) url += `?${params.toString()}`
    const result = await this.request<ListResponse<Session>>(url)
    return result.sessions || []
  }

  // ============= Workflows =============
  async listWorkflows(): Promise<Workflow[]> {
    const result = await this.request<ListResponse<Workflow>>(AppRoutes.ListWorkflows())
    return result.workflows || []
  }

  async getWorkflow(id: string): Promise<Workflow> {
    return this.request<Workflow>(AppRoutes.GetWorkflow(id))
  }

  async createWorkflow(data: CreateWorkflowRequest): Promise<Workflow> {
    return this.request<Workflow>(AppRoutes.CreateWorkflow(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateWorkflow(id: string, data: UpdateWorkflowRequest): Promise<Workflow> {
    return this.request<Workflow>(AppRoutes.UpdateWorkflow(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteWorkflow(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteWorkflow(id), {
      method: "DELETE",
    })
  }

  // ============= Workflow Runs =============
  async listWorkflowRuns(workflowId: string): Promise<WorkflowRun[]> {
    const result = await this.request<{ runs: WorkflowRun[] }>(AppRoutes.ListWorkflowRuns(workflowId))
    return result.runs || []
  }

  async getWorkflowRun(runId: string): Promise<WorkflowRun> {
    return this.request<WorkflowRun>(AppRoutes.GetWorkflowRun(runId))
  }

  async deleteWorkflowRun(runId: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteWorkflowRun(runId), { method: "DELETE" })
  }

  // ============= Tools =============
  async listTools(): Promise<ToolDefinition[]> {
    const result = await this.request<ListResponse<ToolDefinition>>(AppRoutes.ListTools())
    return result.tools || []
  }

  async getTool(id: string): Promise<ToolDefinition> {
    return this.request<ToolDefinition>(AppRoutes.GetTool(id))
  }

  async createTool(data: CreateToolRequest): Promise<ToolDefinition> {
    return this.request<ToolDefinition>(AppRoutes.CreateTool(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateTool(id: string, data: UpdateToolRequest): Promise<ToolDefinition> {
    return this.request<ToolDefinition>(AppRoutes.UpdateTool(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteTool(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteTool(id), {
      method: "DELETE",
    })
  }

  // ============= MCP Servers =============
  async listMCPServers(): Promise<MCPServer[]> {
    const result = await this.request<ListResponse<MCPServer>>(AppRoutes.ListMCPServers())
    return result.mcp_servers || []
  }

  async getMCPServer(id: string): Promise<MCPServer> {
    return this.request<MCPServer>(AppRoutes.GetMCPServer(id))
  }

  async createMCPServer(data: CreateMCPServerRequest): Promise<MCPServer> {
    return this.request<MCPServer>(AppRoutes.CreateMCPServer(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateMCPServer(id: string, data: UpdateMCPServerRequest): Promise<MCPServer> {
    return this.request<MCPServer>(AppRoutes.UpdateMCPServer(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteMCPServer(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteMCPServer(id), {
      method: "DELETE",
    })
  }

  async testMCPServer(id: string): Promise<{ success: boolean; tools: any[]; tools_count: number; error?: string }> {
    return this.request<{ success: boolean; tools: any[]; tools_count: number; error?: string }>(
      AppRoutes.TestMCPServer(id),
      { method: "POST" },
    )
  }

  async testMCPConfig(config: {
    name: string
    transport_type: string
    command?: string
    args?: string[]
    env?: Record<string, string>
    url?: string
    headers?: Record<string, string>
  }): Promise<{ success: boolean; tools: any[]; tools_count: number; error?: string }> {
    return this.request<{ success: boolean; tools: any[]; tools_count: number; error?: string }>(
      AppRoutes.TestMCPConfig(),
      { method: "POST", body: JSON.stringify(config) },
    )
  }

  // ============= Dashboard =============
  async getDashboardSummary(): Promise<DashboardSummary> {
    return this.request<DashboardSummary>(AppRoutes.DashboardSummary())
  }

  // ============= Admin =============
  async listUsers(): Promise<AdminUser[]> {
    const result = await this.request<{ users: AdminUser[] }>(AppRoutes.AdminListUsers())
    return result.users || []
  }

  async createUser(data: CreateUserRequest): Promise<AdminUser> {
    return this.request<AdminUser>(AppRoutes.AdminCreateUser(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateUser(id: string, data: UpdateUserRequest): Promise<AdminUser> {
    return this.request<AdminUser>(AppRoutes.AdminUpdateUser(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteUser(id: string): Promise<void> {
    await this.request<void>(AppRoutes.AdminDeleteUser(id), {
      method: "DELETE",
    })
  }

  // ============= Knowledge Bases =============
  async listKnowledgeBases(): Promise<KnowledgeBase[]> {
    const result = await this.request<{ knowledge_bases: KnowledgeBase[] }>(AppRoutes.ListKnowledgeBases())
    return result.knowledge_bases || []
  }

  async getKnowledgeBase(id: string): Promise<KnowledgeBase> {
    return this.request<KnowledgeBase>(AppRoutes.GetKnowledgeBase(id))
  }

  async createKnowledgeBase(data: CreateKnowledgeBaseRequest): Promise<KnowledgeBase> {
    return this.request<KnowledgeBase>(AppRoutes.CreateKnowledgeBase(), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateKnowledgeBase(id: string, data: UpdateKnowledgeBaseRequest): Promise<KnowledgeBase> {
    return this.request<KnowledgeBase>(AppRoutes.UpdateKnowledgeBase(id), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteKnowledgeBase(id: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteKnowledgeBase(id), {
      method: "DELETE",
    })
  }

  async listKBDocuments(kbId: string): Promise<KBDocument[]> {
    const result = await this.request<{ documents: KBDocument[] }>(AppRoutes.ListKBDocuments(kbId))
    return result.documents || []
  }

  async addKBDocument(kbId: string, data: CreateKBDocumentRequest): Promise<KBDocument> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 10 * 60 * 1000) // 10 minutes
    try {
      return await this.request<KBDocument>(AppRoutes.AddKBDocument(kbId), {
        method: "POST",
        body: JSON.stringify(data),
        signal: controller.signal,
      })
    } finally {
      clearTimeout(timeoutId)
    }
  }

  async deleteKBDocument(kbId: string, docId: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteKBDocument(kbId, docId), {
      method: "DELETE",
    })
  }

  // ============= Workflow Schedules =============
  async listWorkflowSchedules(workflowId: string): Promise<WorkflowSchedule[]> {
    const result = await this.request<{ schedules: WorkflowSchedule[] }>(
      AppRoutes.ListWorkflowSchedules(workflowId),
    )
    return result.schedules || []
  }

  async createWorkflowSchedule(workflowId: string, data: CreateWorkflowScheduleRequest): Promise<WorkflowSchedule> {
    return this.request<WorkflowSchedule>(AppRoutes.CreateWorkflowSchedule(workflowId), {
      method: "POST",
      body: JSON.stringify(data),
    })
  }

  async updateWorkflowSchedule(scheduleId: string, data: UpdateWorkflowScheduleRequest): Promise<WorkflowSchedule> {
    return this.request<WorkflowSchedule>(AppRoutes.UpdateWorkflowSchedule(scheduleId), {
      method: "PUT",
      body: JSON.stringify(data),
    })
  }

  async deleteWorkflowSchedule(scheduleId: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteWorkflowSchedule(scheduleId), {
      method: "DELETE",
    })
  }

  // ============= Agent Memory =============
  async listAgentMemories(agentId: string): Promise<AgentMemory[]> {
    const result = await this.request<{ memories: AgentMemory[] }>(
      AppRoutes.ListAgentMemories(agentId),
    )
    return result.memories || []
  }

  async deleteAgentMemory(agentId: string, memoryId: string): Promise<void> {
    await this.request<void>(AppRoutes.DeleteAgentMemory(agentId, memoryId), {
      method: "DELETE",
    })
  }

  async clearAgentMemories(agentId: string): Promise<void> {
    await this.request<void>(AppRoutes.ClearAgentMemories(agentId), {
      method: "DELETE",
    })
  }

  // ============= Traces =============
  async getSessionTrace(sessionId: string): Promise<SessionTrace> {
    return this.request<SessionTrace>(AppRoutes.GetSessionTrace(sessionId))
  }

  async getWorkflowRunTrace(runId: string): Promise<WorkflowRunTrace> {
    return this.request<WorkflowRunTrace>(AppRoutes.GetWorkflowRunTrace(runId))
  }
}

export const apiClient = new ApiClient()
