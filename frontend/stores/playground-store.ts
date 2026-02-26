import { create } from "zustand"
import { apiClient } from "@/lib/api-client"
import type { LLMProvider, Agent, Team, Session, Message, ToolCall, AgentStep, ToolRound, MCPServer, FileNode, PlanData, HITLApprovalEvent, ToolProposalEvent, Artifact, ArtifactType } from "@/types/playground"

interface PlaygroundState {
  // Sidebar
  sidebarOpen: boolean
  mode: "agent" | "team"

  // Selected entities
  selectedProviderId: string | null
  selectedAgentId: string | null
  selectedTeamId: string | null
  selectedSessionId: string | null

  // Data
  providers: LLMProvider[]
  agents: Agent[]
  teams: Team[]
  sessions: Session[]
  messages: Message[]

  mcpServers: MCPServer[]

  // Loading states
  isLoadingProviders: boolean
  isLoadingAgents: boolean
  isLoadingTeams: boolean
  isLoadingSessions: boolean
  isLoadingMessages: boolean

  // Streaming
  isStreaming: boolean
  streamingContent: string
  streamingReasoning: string
  streamingToolCalls: ToolCall[]
  streamingAgentStep: AgentStep | null
  streamingToolRound: ToolRound | null
  streamingKBContext: { id: string; name: string }[]
  abortController: AbortController | null

  // AI Elements streaming state
  streamingTerminal: string
  streamingTerminalComplete: boolean
  streamingFileTree: FileNode[] | null
  streamingSourceUrls: { url: string; title?: string }[]
  streamingPlan: PlanData | null
  streamingJsx: string
  streamingJsxComplete: boolean

  // Artifacts
  artifacts: Artifact[]
  activeArtifactId: string | null
  artifactPanelOpen: boolean
  // Streaming artifact (partial, before is_complete)
  streamingArtifact: { id: string; title: string; type: ArtifactType; content: string } | null

  // Token tracking
  sessionTokens: { input: number; output: number } | null

  // HITL
  pendingHITLApproval: HITLApprovalEvent | null
  setHITLApprovalRequired: (event: HITLApprovalEvent | null) => void

  // Tool Proposals
  pendingToolProposal: ToolProposalEvent | null
  setPendingToolProposal: (event: ToolProposalEvent | null) => void
  generatingTool: { name: string; handler_type: string } | null
  setGeneratingTool: (event: { name: string; handler_type: string } | null) => void

  // Actions
  setSidebarOpen: (open: boolean) => void
  toggleSidebar: () => void
  setMode: (mode: "agent" | "team") => void
  setSelectedProvider: (id: string | null) => void
  setSelectedAgent: (id: string | null) => void
  setSelectedTeam: (id: string | null) => void
  setSelectedSession: (id: string | null) => void
  setProviders: (providers: LLMProvider[]) => void
  setAgents: (agents: Agent[]) => void
  setTeams: (teams: Team[]) => void
  setMCPServers: (mcpServers: MCPServer[]) => void
  setSessions: (sessions: Session[]) => void
  setMessages: (messages: Message[]) => void
  addMessage: (message: Message) => void
  updateLastMessage: (updates: Partial<Message>) => void
  setIsStreaming: (streaming: boolean) => void
  setStreamingContent: (content: string) => void
  appendStreamingContent: (chunk: string) => void
  setStreamingReasoning: (reasoning: string) => void
  appendStreamingReasoning: (chunk: string) => void
  setStreamingToolCalls: (toolCalls: ToolCall[]) => void
  upsertStreamingToolCall: (toolCall: ToolCall) => void
  setStreamingAgentStep: (step: AgentStep | null) => void
  setStreamingToolRound: (round: ToolRound | null) => void
  setStreamingKBContext: (kbs: { id: string; name: string }[]) => void
  setAbortController: (controller: AbortController | null) => void

  // AI Elements actions
  appendStreamingTerminal: (chunk: string) => void
  setStreamingTerminalComplete: (v: boolean) => void
  setStreamingFileTree: (nodes: FileNode[] | null) => void
  addStreamingSourceUrl: (url: string, title?: string) => void
  setStreamingPlan: (plan: PlanData | null) => void
  appendStreamingPlanStep: (step: string) => void
  completePlan: () => void
  setStreamingJsx: (jsx: string, complete: boolean) => void

  // Artifact actions
  upsertArtifact: (artifact: { id: string; title: string; type: ArtifactType; content: string; sessionId: string }) => void
  updateArtifactContent: (id: string, content: string) => void
  removeArtifact: (id: string) => void
  setActiveArtifactId: (id: string | null) => void
  setArtifactPanelOpen: (open: boolean) => void
  clearArtifacts: () => void
  setStreamingArtifact: (artifact: { id: string; title: string; type: ArtifactType; content: string } | null) => void

  // Token tracking actions
  setSessionTokens: (tokens: { input: number; output: number } | null) => void
  updateSessionTokensInList: (sessionId: string, input: number, output: number) => void

  clearChat: () => void
  reset: () => void

  // Async actions
  fetchProviders: () => Promise<void>
  fetchAgents: () => Promise<void>
  fetchTeams: () => Promise<void>
  fetchSessions: () => Promise<void>
  fetchSessionMessages: (sessionId: string) => Promise<void>
  createSession: (entityType: "agent" | "team", entityId: string, title?: string) => Promise<Session | null>
  deleteSession: (sessionId: string) => Promise<void>
  deleteAgent: (agentId: string) => Promise<void>
  deleteTeam: (teamId: string) => Promise<void>
  deleteProvider: (providerId: string) => Promise<void>
  fetchMCPServers: () => Promise<void>
  deleteMCPServer: (serverId: string) => Promise<void>
}

export const usePlaygroundStore = create<PlaygroundState>((set, get) => ({
  // Initial state
  sidebarOpen: true,
  mode: "agent",
  selectedProviderId: null,
  selectedAgentId: null,
  selectedTeamId: null,
  selectedSessionId: null,
  providers: [],
  agents: [],
  teams: [],
  sessions: [],
  mcpServers: [],
  messages: [],
  isLoadingProviders: false,
  isLoadingAgents: false,
  isLoadingTeams: false,
  isLoadingSessions: false,
  isLoadingMessages: false,
  isStreaming: false,
  streamingContent: "",
  streamingReasoning: "",
  streamingToolCalls: [],
  streamingAgentStep: null,
  streamingToolRound: null,
  streamingKBContext: [],
  abortController: null,

  // AI Elements initial state
  streamingTerminal: "",
  streamingTerminalComplete: false,
  streamingFileTree: null,
  streamingSourceUrls: [],
  streamingPlan: null,
  streamingJsx: "",
  streamingJsxComplete: false,

  // Artifact initial state
  artifacts: [],
  activeArtifactId: null,
  artifactPanelOpen: false,
  streamingArtifact: null,

  // Token tracking initial state
  sessionTokens: null,

  // HITL initial state
  pendingHITLApproval: null,
  setHITLApprovalRequired: (event) => set({ pendingHITLApproval: event }),

  // Tool Proposals initial state
  pendingToolProposal: null,
  setPendingToolProposal: (event) => set({ pendingToolProposal: event }),
  generatingTool: null,
  setGeneratingTool: (event) => set({ generatingTool: event }),

  // Actions
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setMode: (mode) => set({ mode, selectedSessionId: null, messages: [] }),
  setSelectedProvider: (id) => set({ selectedProviderId: id }),
  setSelectedAgent: (id) => set({ selectedAgentId: id, selectedSessionId: null, messages: [], artifacts: [], activeArtifactId: null, artifactPanelOpen: false, streamingArtifact: null }),
  setSelectedTeam: (id) => set({ selectedTeamId: id, selectedSessionId: null, messages: [], artifacts: [], activeArtifactId: null, artifactPanelOpen: false, streamingArtifact: null }),
  setSelectedSession: (id) => set({ selectedSessionId: id, artifacts: [], activeArtifactId: null, artifactPanelOpen: false, streamingArtifact: null }),
  setProviders: (providers) => set({ providers }),
  setAgents: (agents) => set({ agents }),
  setTeams: (teams) => set({ teams }),
  setMCPServers: (mcpServers) => set({ mcpServers }),
  setSessions: (sessions) => set({ sessions }),
  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),
  updateLastMessage: (updates) =>
    set((s) => {
      const msgs = [...s.messages]
      if (msgs.length > 0) {
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...updates }
      }
      return { messages: msgs }
    }),
  setIsStreaming: (streaming) => set({ isStreaming: streaming }),
  setStreamingContent: (content) => set({ streamingContent: content }),
  appendStreamingContent: (chunk) =>
    set((s) => ({ streamingContent: s.streamingContent + chunk })),
  setStreamingReasoning: (reasoning) => set({ streamingReasoning: reasoning }),
  appendStreamingReasoning: (chunk) =>
    set((s) => ({ streamingReasoning: s.streamingReasoning + chunk })),
  setStreamingToolCalls: (toolCalls) => set({ streamingToolCalls: toolCalls }),
  upsertStreamingToolCall: (toolCall) =>
    set((s) => {
      const existing = s.streamingToolCalls.findIndex((tc) => tc.id === toolCall.id)
      if (existing >= 0) {
        const updated = [...s.streamingToolCalls]
        updated[existing] = toolCall
        return { streamingToolCalls: updated }
      }
      return { streamingToolCalls: [...s.streamingToolCalls, toolCall] }
    }),
  setStreamingAgentStep: (step) => set({ streamingAgentStep: step }),
  setStreamingToolRound: (round) => set({ streamingToolRound: round }),
  setStreamingKBContext: (kbs) => set({ streamingKBContext: kbs }),
  setAbortController: (controller) => set({ abortController: controller }),

  // AI Elements actions
  appendStreamingTerminal: (chunk) =>
    set((s) => ({ streamingTerminal: s.streamingTerminal + chunk })),
  setStreamingTerminalComplete: (v) => set({ streamingTerminalComplete: v }),
  setStreamingFileTree: (nodes) => set({ streamingFileTree: nodes }),
  addStreamingSourceUrl: (url, title) =>
    set((s) => ({ streamingSourceUrls: [...s.streamingSourceUrls, { url, title }] })),
  setStreamingPlan: (plan) => set({ streamingPlan: plan }),
  appendStreamingPlanStep: (step) =>
    set((s) => ({
      streamingPlan: s.streamingPlan
        ? { ...s.streamingPlan, steps: [...s.streamingPlan.steps, step] }
        : { title: "Plan", steps: [step], isComplete: false },
    })),
  completePlan: () =>
    set((s) => ({
      streamingPlan: s.streamingPlan ? { ...s.streamingPlan, isComplete: true } : null,
    })),
  setStreamingJsx: (jsx, complete) => set({ streamingJsx: jsx, streamingJsxComplete: complete }),

  // Artifact actions
  upsertArtifact: ({ id, title, type, content, sessionId }) =>
    set((s) => {
      const now = new Date().toISOString()
      const existing = s.artifacts.find((a) => a.id === id)
      const updated = existing
        ? s.artifacts.map((a) => a.id === id ? { ...a, title, type, content, updatedAt: now } : a)
        : [...s.artifacts, { id, title, type, content, sessionId, createdAt: now, updatedAt: now }]
      return {
        artifacts: updated,
        activeArtifactId: id,
        artifactPanelOpen: true,
      }
    }),
  updateArtifactContent: (id, content) =>
    set((s) => ({
      artifacts: s.artifacts.map((a) => a.id === id ? { ...a, content, updatedAt: new Date().toISOString() } : a),
    })),
  removeArtifact: (id) =>
    set((s) => {
      const remaining = s.artifacts.filter((a) => a.id !== id)
      const newActive = s.activeArtifactId === id
        ? (remaining[remaining.length - 1]?.id ?? null)
        : s.activeArtifactId
      return {
        artifacts: remaining,
        activeArtifactId: newActive,
        artifactPanelOpen: remaining.length > 0 ? s.artifactPanelOpen : false,
      }
    }),
  setActiveArtifactId: (id) => set({ activeArtifactId: id }),
  setArtifactPanelOpen: (open) => set({ artifactPanelOpen: open }),
  clearArtifacts: () => set({ artifacts: [], activeArtifactId: null, artifactPanelOpen: false, streamingArtifact: null }),
  setStreamingArtifact: (artifact) =>
    set((s) => ({
      streamingArtifact: artifact,
      // Open panel when streaming starts; keep it open when clearing if we have completed artifacts
      artifactPanelOpen: artifact !== null ? true : s.artifacts.length > 0 ? s.artifactPanelOpen : false,
    })),

  // Token tracking actions
  setSessionTokens: (tokens) => set({ sessionTokens: tokens }),
  updateSessionTokensInList: (sessionId, input, output) =>
    set((s) => ({
      sessions: s.sessions.map((sess) =>
        sess.id === sessionId
          ? { ...sess, total_input_tokens: input, total_output_tokens: output }
          : sess
      ),
      sessionTokens: { input, output },
    })),

  clearChat: () => set({
    messages: [], selectedSessionId: null,
    streamingContent: "", streamingReasoning: "", streamingToolCalls: [],
    streamingAgentStep: null, streamingToolRound: null, streamingKBContext: [],
    streamingTerminal: "", streamingTerminalComplete: false, streamingFileTree: null,
    streamingSourceUrls: [], streamingPlan: null, streamingJsx: "", streamingJsxComplete: false,
    sessionTokens: null, pendingHITLApproval: null, pendingToolProposal: null, generatingTool: null,
    artifacts: [], activeArtifactId: null, artifactPanelOpen: false, streamingArtifact: null,
  }),
  reset: () =>
    set({
      sidebarOpen: true,
      mode: "agent",
      selectedProviderId: null,
      selectedAgentId: null,
      selectedTeamId: null,
      selectedSessionId: null,
      providers: [],
      agents: [],
      teams: [],
      sessions: [],
      mcpServers: [],
      messages: [],
      isLoadingProviders: false,
      isLoadingAgents: false,
      isLoadingTeams: false,
      isLoadingSessions: false,
      isLoadingMessages: false,
      isStreaming: false,
      streamingContent: "",
      streamingReasoning: "",
      streamingToolCalls: [],
      streamingAgentStep: null,
      streamingToolRound: null,
      streamingKBContext: [],
      abortController: null,
      streamingTerminal: "",
      streamingTerminalComplete: false,
      streamingFileTree: null,
      streamingSourceUrls: [],
      streamingPlan: null,
      streamingJsx: "",
      streamingJsxComplete: false,
      pendingHITLApproval: null,
      pendingToolProposal: null,
      generatingTool: null,
      artifacts: [],
      activeArtifactId: null,
      artifactPanelOpen: false,
      streamingArtifact: null,
    }),

  // Async actions
  fetchProviders: async () => {
    set({ isLoadingProviders: true })
    try {
      const providers = await apiClient.listProviders()
      set({ providers, isLoadingProviders: false })
    } catch (error) {
      console.error("Failed to fetch providers:", error)
      set({ isLoadingProviders: false })
    }
  },

  fetchAgents: async () => {
    set({ isLoadingAgents: true })
    try {
      const agents = await apiClient.listAgents()
      set({ agents, isLoadingAgents: false })
    } catch (error) {
      console.error("Failed to fetch agents:", error)
      set({ isLoadingAgents: false })
    }
  },

  fetchTeams: async () => {
    set({ isLoadingTeams: true })
    try {
      const teams = await apiClient.listTeams()
      set({ teams, isLoadingTeams: false })
    } catch (error) {
      console.error("Failed to fetch teams:", error)
      set({ isLoadingTeams: false })
    }
  },

  fetchSessions: async () => {
    set({ isLoadingSessions: true })
    try {
      const sessions = await apiClient.listSessions()
      set({ sessions, isLoadingSessions: false })
    } catch (error) {
      console.error("Failed to fetch sessions:", error)
      set({ isLoadingSessions: false })
    }
  },

  fetchSessionMessages: async (sessionId: string) => {
    set({ isLoadingMessages: true })
    try {
      const messages = await apiClient.getSessionMessages(sessionId)
      // Rehydrate artifacts from message history so chips are clickable when returning to a session
      const ARTIFACT_RE = /<artifact\s+([^>]*)>([\s\S]*?)<\/artifact>/g
      const ATTR_RE = /(\w[\w-]*)\s*=\s*"([^"]*)"/g
      // seenById: canonical map of id→artifact; seenByTitle: title→canonical id for dedup
      const seenById = new Map<string, Artifact>()
      const seenByTitle = new Map<string, string>() // normalised title → canonical id
      for (const msg of messages) {
        if (msg.role !== "assistant" || !msg.content) continue
        let m: RegExpExecArray | null
        ARTIFACT_RE.lastIndex = 0
        while ((m = ARTIFACT_RE.exec(msg.content)) !== null) {
          const attrs: Record<string, string> = {}
          let a: RegExpExecArray | null
          const attrRe = new RegExp(ATTR_RE.source, "g")
          while ((a = attrRe.exec(m[1])) !== null) attrs[a[1]] = a[2]
          if (!attrs.id) continue
          const title = attrs.title ?? "Artifact"
          const normTitle = title.trim().toLowerCase()
          // If a different id produced the same title before, fold this into the canonical id
          const canonicalId = seenByTitle.get(normTitle) ?? attrs.id
          seenByTitle.set(normTitle, canonicalId)
          seenById.set(canonicalId, {
            id: canonicalId,
            title,
            type: (attrs.type ?? "text") as ArtifactType,
            content: m[2].trim(),
            sessionId,
            createdAt: seenById.get(canonicalId)?.createdAt ?? msg.created_at ?? new Date().toISOString(),
            updatedAt: msg.created_at ?? new Date().toISOString(),
          })
        }
      }
      const artifacts = [...seenById.values()]
      set({
        messages,
        isLoadingMessages: false,
        artifacts,
        activeArtifactId: artifacts.length > 0 ? artifacts[artifacts.length - 1].id : null,
        artifactPanelOpen: false, // don't auto-open on load, let user click the chip
      })
    } catch (error) {
      console.error("Failed to fetch session messages:", error)
      set({ isLoadingMessages: false })
    }
  },

  createSession: async (entityType: "agent" | "team", entityId: string, title?: string) => {
    try {
      const session = await apiClient.createSession({ entity_type: entityType, entity_id: entityId, title })
      const state = get()
      set({ sessions: [...state.sessions, session], selectedSessionId: session.id })
      return session
    } catch (error) {
      console.error("Failed to create session:", error)
      return null
    }
  },

  deleteSession: async (sessionId: string) => {
    try {
      await apiClient.deleteSession(sessionId)
      const state = get()
      set({ sessions: state.sessions.filter((s) => s.id !== sessionId) })
      if (state.selectedSessionId === sessionId) {
        set({ selectedSessionId: null, messages: [], artifacts: [], activeArtifactId: null, artifactPanelOpen: false, streamingArtifact: null })
      }
    } catch (error) {
      console.error("Failed to delete session:", error)
    }
  },

  deleteAgent: async (agentId: string) => {
    try {
      await apiClient.deleteAgent(agentId)
      const state = get()
      set({ agents: state.agents.filter((a) => a.id !== agentId) })
      if (state.selectedAgentId === agentId) {
        set({ selectedAgentId: null, selectedSessionId: null, messages: [] })
      }
    } catch (error) {
      console.error("Failed to delete agent:", error)
      throw error
    }
  },

  deleteTeam: async (teamId: string) => {
    try {
      await apiClient.deleteTeam(teamId)
      const state = get()
      set({ teams: state.teams.filter((t) => t.id !== teamId) })
      if (state.selectedTeamId === teamId) {
        set({ selectedTeamId: null, selectedSessionId: null, messages: [] })
      }
    } catch (error) {
      console.error("Failed to delete team:", error)
      throw error
    }
  },

  deleteProvider: async (providerId: string) => {
    try {
      await apiClient.deleteProvider(providerId)
      const state = get()
      set({ providers: state.providers.filter((p) => p.id !== providerId) })
      if (state.selectedProviderId === providerId) {
        set({ selectedProviderId: null })
      }
    } catch (error) {
      console.error("Failed to delete provider:", error)
      throw error
    }
  },

  fetchMCPServers: async () => {
    try {
      const mcpServers = await apiClient.listMCPServers()
      set({ mcpServers })
    } catch (error) {
      console.error("Failed to fetch MCP servers:", error)
    }
  },

  deleteMCPServer: async (serverId: string) => {
    try {
      await apiClient.deleteMCPServer(serverId)
      const state = get()
      set({ mcpServers: state.mcpServers.filter((s) => s.id !== serverId) })
    } catch (error) {
      console.error("Failed to delete MCP server:", error)
      throw error
    }
  },
}))
