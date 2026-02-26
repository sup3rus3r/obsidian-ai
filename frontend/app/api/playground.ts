import { AppRoutes } from "./routes"
import type {
  LLMProvider,
  Agent,
  Team,
  Workflow,
  Session,
  Message,
  Secret,
  CreateProviderRequest,
  CreateAgentRequest,
  UpdateAgentRequest,
  CreateTeamRequest,
  CreateWorkflowRequest,
  CreateSessionRequest,
} from "@/types/playground"

function headers(accessToken: string) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${accessToken}`,
  }
}

async function throwWithDetail(res: Response, fallback: string): Promise<never> {
  const err = await res.json().catch(() => ({ detail: fallback }))
  throw new Error(err.detail || `${fallback} (HTTP ${res.status})`)
}

// ============================================================================
// Providers
// ============================================================================

export async function listProviders(accessToken: string): Promise<LLMProvider[]> {
  const res = await fetch(AppRoutes.ListProviders(), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list providers")
  const data = await res.json()
  return data.providers
}

export async function createProvider(accessToken: string, data: CreateProviderRequest): Promise<LLMProvider> {
  const res = await fetch(AppRoutes.CreateProvider(), {
    method: "POST",
    headers: headers(accessToken),
    body: JSON.stringify(data),
  })
  if (!res.ok) await throwWithDetail(res, "Failed to create provider")
  return res.json()
}

export async function deleteProvider(accessToken: string, id: string): Promise<void> {
  const res = await fetch(AppRoutes.DeleteProvider(id), {
    method: "DELETE",
    headers: headers(accessToken),
  })
  if (!res.ok) throw new Error("Failed to delete provider")
}

export async function testProvider(accessToken: string, id: string): Promise<{ status: string }> {
  const res = await fetch(AppRoutes.TestProvider(id), {
    method: "POST",
    headers: headers(accessToken),
  })
  if (!res.ok) throw new Error("Failed to test provider")
  return res.json()
}

export async function listModels(accessToken: string, id: string): Promise<{ id: string; name: string }[]> {
  const res = await fetch(AppRoutes.ListModels(id), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list models")
  const data = await res.json()
  return data.models
}

// ============================================================================
// Secrets (for provider API key selection)
// ============================================================================

export async function listSecrets(accessToken: string): Promise<Secret[]> {
  const res = await fetch(AppRoutes.ListSecrets(), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list secrets")
  const data = await res.json()
  return data.secrets
}

// ============================================================================
// Agents
// ============================================================================

export async function listAgents(accessToken: string): Promise<Agent[]> {
  const res = await fetch(AppRoutes.ListAgents(), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list agents")
  const data = await res.json()
  return data.agents
}

export async function createAgent(accessToken: string, data: CreateAgentRequest): Promise<Agent> {
  const res = await fetch(AppRoutes.CreateAgent(), {
    method: "POST",
    headers: headers(accessToken),
    body: JSON.stringify(data),
  })
  if (!res.ok) await throwWithDetail(res, "Failed to create agent")
  return res.json()
}

export async function updateAgent(accessToken: string, id: string, data: UpdateAgentRequest): Promise<Agent> {
  const res = await fetch(AppRoutes.UpdateAgent(id), {
    method: "PUT",
    headers: headers(accessToken),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to update agent")
  return res.json()
}

export async function deleteAgent(accessToken: string, id: string): Promise<void> {
  const res = await fetch(AppRoutes.DeleteAgent(id), {
    method: "DELETE",
    headers: headers(accessToken),
  })
  if (!res.ok) throw new Error("Failed to delete agent")
}

// ============================================================================
// Teams
// ============================================================================

export async function listTeams(accessToken: string): Promise<Team[]> {
  const res = await fetch(AppRoutes.ListTeams(), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list teams")
  const data = await res.json()
  return data.teams
}

export async function createTeam(accessToken: string, data: CreateTeamRequest): Promise<Team> {
  const res = await fetch(AppRoutes.CreateTeam(), {
    method: "POST",
    headers: headers(accessToken),
    body: JSON.stringify(data),
  })
  if (!res.ok) await throwWithDetail(res, "Failed to create team")
  return res.json()
}

export async function deleteTeam(accessToken: string, id: string): Promise<void> {
  const res = await fetch(AppRoutes.DeleteTeam(id), {
    method: "DELETE",
    headers: headers(accessToken),
  })
  if (!res.ok) throw new Error("Failed to delete team")
}

// ============================================================================
// Sessions
// ============================================================================

export async function listSessions(
  accessToken: string,
  entityType?: string,
  entityId?: string,
): Promise<Session[]> {
  let url = AppRoutes.ListSessions()
  const params = new URLSearchParams()
  if (entityType) params.set("entity_type", entityType)
  if (entityId) params.set("entity_id", entityId)
  if (params.toString()) url += `?${params.toString()}`

  const res = await fetch(url, { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list sessions")
  const data = await res.json()
  return data.sessions
}

export async function createSession(accessToken: string, data: CreateSessionRequest): Promise<Session> {
  const res = await fetch(AppRoutes.CreateSession(), {
    method: "POST",
    headers: headers(accessToken),
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error("Failed to create session")
  return res.json()
}

export async function getSessionMessages(accessToken: string, sessionId: string): Promise<Message[]> {
  const res = await fetch(AppRoutes.GetSessionMessages(sessionId), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to get messages")
  const data = await res.json()
  return data.messages
}

export async function deleteSession(accessToken: string, id: string): Promise<void> {
  const res = await fetch(AppRoutes.DeleteSession(id), {
    method: "DELETE",
    headers: headers(accessToken),
  })
  if (!res.ok) throw new Error("Failed to delete session")
}

// ============================================================================
// Workflows
// ============================================================================

export async function listWorkflows(accessToken: string): Promise<Workflow[]> {
  const res = await fetch(AppRoutes.ListWorkflows(), { headers: headers(accessToken) })
  if (!res.ok) throw new Error("Failed to list workflows")
  const data = await res.json()
  return data.workflows
}

export async function createWorkflow(accessToken: string, data: CreateWorkflowRequest): Promise<Workflow> {
  const res = await fetch(AppRoutes.CreateWorkflow(), {
    method: "POST",
    headers: headers(accessToken),
    body: JSON.stringify(data),
  })
  if (!res.ok) await throwWithDetail(res, "Failed to create workflow")
  return res.json()
}

export async function deleteWorkflow(accessToken: string, id: string): Promise<void> {
  const res = await fetch(AppRoutes.DeleteWorkflow(id), {
    method: "DELETE",
    headers: headers(accessToken),
  })
  if (!res.ok) throw new Error("Failed to delete workflow")
}
