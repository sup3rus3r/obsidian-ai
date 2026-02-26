import { create } from "zustand"
import { apiClient } from "@/lib/api-client"
import type { Agent, Team, Workflow, Session, DashboardSummary } from "@/types/playground"

interface DashboardState {
  agents: Agent[]
  teams: Team[]
  workflows: Workflow[]
  sessions: Session[]
  summary: DashboardSummary | null
  isLoading: boolean

  fetchAll: () => Promise<void>
  fetchWorkflows: () => Promise<void>
  deleteWorkflow: (id: string) => Promise<void>
  deleteAgent: (id: string) => Promise<void>
  deleteTeam: (id: string) => Promise<void>
}

export const useDashboardStore = create<DashboardState>((set) => ({
  agents: [],
  teams: [],
  workflows: [],
  sessions: [],
  summary: null,
  isLoading: false,

  fetchAll: async () => {
    set({ isLoading: true })
    try {
      const [agents, teams, workflows, sessions, summary] = await Promise.all([
        apiClient.listAgents(),
        apiClient.listTeams(),
        apiClient.listWorkflows(),
        apiClient.listSessions(),
        apiClient.getDashboardSummary(),
      ])
      set({ agents, teams, workflows, sessions, summary, isLoading: false })
    } catch (error) {
      console.error("Failed to fetch dashboard data:", error)
      set({ isLoading: false })
    }
  },

  fetchWorkflows: async () => {
    try {
      const workflows = await apiClient.listWorkflows()
      set({ workflows })
    } catch (error) {
      console.error("Failed to fetch workflows:", error)
    }
  },

  deleteWorkflow: async (id: string) => {
    try {
      await apiClient.deleteWorkflow(id)
      set((s) => ({ workflows: s.workflows.filter((w) => w.id !== id) }))
    } catch (error) {
      console.error("Failed to delete workflow:", error)
      throw error
    }
  },

  deleteAgent: async (id: string) => {
    try {
      await apiClient.deleteAgent(id)
      set((s) => ({ agents: s.agents.filter((a) => a.id !== id) }))
    } catch (error) {
      console.error("Failed to delete agent:", error)
      throw error
    }
  },

  deleteTeam: async (id: string) => {
    try {
      await apiClient.deleteTeam(id)
      set((s) => ({ teams: s.teams.filter((t) => t.id !== id) }))
    } catch (error) {
      console.error("Failed to delete team:", error)
      throw error
    }
  },
}))
