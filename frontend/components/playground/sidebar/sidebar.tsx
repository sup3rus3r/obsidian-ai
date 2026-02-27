"use client"

import { useRef, useState } from "react"
import { toast } from "sonner"
import { EndpointConfig } from "./endpoint-config"
import { ModeToggle } from "./mode-toggle"
import { EntitySelector } from "./entity-selector"
import { SessionHistory } from "./session-history"
import { ToolsSelector } from "./tools-selector"
import { MCPServersSelector } from "./mcp-servers-selector"
import { ProviderDialog } from "../dialogs/provider-dialog"
import { AgentDialog } from "../dialogs/agent-dialog"
import { TeamDialog } from "../dialogs/team-dialog"
import { ToolDialog } from "@/components/dialogs/tool-dialog"
import { MCPServerDialog } from "@/components/dialogs/mcp-server-dialog"
import { usePlaygroundStore } from "@/stores/playground-store"
import { usePermissionsStore } from "@/stores/permissions-store"
import { apiClient } from "@/lib/api-client"
import type { Agent, LLMProvider, MCPServer, Team } from "@/types/playground"

export function Sidebar() {
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)
  const providers = usePlaygroundStore((s) => s.providers)
  const setAgents = usePlaygroundStore((s) => s.setAgents)
  const setProviders = usePlaygroundStore((s) => s.setProviders)
  const setSelectedAgent = usePlaygroundStore((s) => s.setSelectedAgent)
  const teams = usePlaygroundStore((s) => s.teams)
  const permissions = usePermissionsStore((s) => s.permissions)
  const [providerDialogOpen, setProviderDialogOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<LLMProvider | null>(null)
  const [agentDialogOpen, setAgentDialogOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [teamDialogOpen, setTeamDialogOpen] = useState(false)
  const [editingTeam, setEditingTeam] = useState<Team | null>(null)
  const [toolDialogOpen, setToolDialogOpen] = useState(false)
  const [mcpServerDialogOpen, setMCPServerDialogOpen] = useState(false)
  const [editingMCPServer, setEditingMCPServer] = useState<MCPServer | null>(null)
  const importInputRef = useRef<HTMLInputElement>(null)
  const providerImportInputRef = useRef<HTMLInputElement>(null)

  const handleEditProvider = (providerId: string) => {
    const provider = providers.find((p) => p.id === providerId)
    if (provider) {
      setEditingProvider(provider)
      setProviderDialogOpen(true)
    }
  }

  const handleProviderUpdated = (updated: LLMProvider) => {
    setProviders(providers.map((p) => (p.id === updated.id ? updated : p)))
    toast.success(`Provider "${updated.name}" updated`)
  }

  const handleExportProvider = async (providerId: string, providerName: string) => {
    try {
      await apiClient.exportProvider(providerId, providerName)
      toast.success(`Exported "${providerName}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed")
    }
  }

  const handleExportAllProviders = async () => {
    try {
      await apiClient.exportAllProviders()
      toast.success(`Exported ${providers.length} provider${providers.length !== 1 ? "s" : ""}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed")
    }
  }

  const handleImportProvider = () => {
    providerImportInputRef.current?.click()
  }

  const handleProviderImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ""
    try {
      const text = await file.text()
      const parsed = JSON.parse(text)
      // Re-create File from the already-read text so the API client can send it as FormData
      const reFile = new File([text], file.name, { type: "application/json" })
      if (parsed.provider) {
        const { provider, warnings } = await apiClient.importProvider(reFile)
        setProviders([...providers, provider])
        toast.success(`Imported "${provider.name}" — add an API key to activate`)
        warnings.forEach((w) => toast.warning(w))
      } else if (parsed.providers) {
        const { providers: imported, warnings } = await apiClient.importProvidersBulk(reFile)
        setProviders([...providers, ...imported])
        toast.success(`Imported ${imported.length} provider${imported.length !== 1 ? "s" : ""} — add API keys to activate`)
        warnings.forEach((w) => toast.warning(w))
      } else {
        toast.error("Invalid provider export file")
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed")
    }
  }

  const handleEditAgent = (agentId: string) => {
    const agent = agents.find((a) => a.id === agentId)
    if (agent) {
      setEditingAgent(agent)
      setAgentDialogOpen(true)
    }
  }

  const handleEditTeam = (teamId: string) => {
    const team = teams.find((t) => t.id === teamId)
    if (team) {
      setEditingTeam(team)
      setTeamDialogOpen(true)
    }
  }

  const handleExportAgent = async (agentId: string, agentName: string) => {
    try {
      await apiClient.exportAgent(agentId, agentName)
      toast.success(`Exported "${agentName}"`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Export failed")
    }
  }

  const handleImportAgent = () => {
    importInputRef.current?.click()
  }

  const handleImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    // Reset so the same file can be re-imported if needed
    e.target.value = ""
    try {
      const { agent, warnings } = await apiClient.importAgent(file)
      setAgents([...agents, agent])
      setSelectedAgent(agent.id)
      toast.success(`Imported "${agent.name}"`)
      if (warnings.length > 0) {
        warnings.forEach((w) => toast.warning(w))
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Import failed")
    }
  }

  return (
    <>
      {/* Hidden file input for agent import */}
      <input
        ref={importInputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleImportFileChange}
      />
      {/* Hidden file input for provider import (single + bulk auto-detected) */}
      <input
        ref={providerImportInputRef}
        type="file"
        accept=".json"
        className="hidden"
        onChange={handleProviderImportFileChange}
      />

      <div className="flex flex-col h-full w-88 min-w-0 bg-sidebar text-sidebar-foreground overflow-hidden">
        <div className="flex-1 overflow-y-auto overflow-x-hidden">
          <div className="flex flex-col gap-4 p-3">
            <EndpointConfig
              onAddProvider={() => { setEditingProvider(null); setProviderDialogOpen(true) }}
              onEditProvider={permissions.manage_providers ? handleEditProvider : undefined}
              onExportProvider={handleExportProvider}
              onImportProvider={permissions.manage_providers ? handleImportProvider : undefined}
              onExportAllProviders={handleExportAllProviders}
              hideAdd={!permissions.manage_providers}
            />
            <ModeToggle />
            <EntitySelector
              onAddAgent={() => setAgentDialogOpen(true)}
              onAddTeam={() => { setEditingTeam(null); setTeamDialogOpen(true) }}
              onEditAgent={handleEditAgent}
              onEditTeam={permissions.create_teams ? handleEditTeam : undefined}
              onExportAgent={handleExportAgent}
              onImportAgent={permissions.create_agents ? handleImportAgent : undefined}
              hideAddAgent={!permissions.create_agents}
              hideAddTeam={!permissions.create_teams}
              hideEditAgent={!permissions.create_agents}
              hideEditTeam={!permissions.create_teams}
              hideDeleteAgent={!permissions.create_agents}
              hideDeleteTeam={!permissions.create_teams}
            />

            {mode === "agent" && (
              <>
                <ToolsSelector
                  onCreateTool={() => setToolDialogOpen(true)}
                  hideCreate={!permissions.create_tools}
                />
                <MCPServersSelector
                  onAddServer={() => setMCPServerDialogOpen(true)}
                  onEditServer={(server) => {
                    setEditingMCPServer(server)
                    setMCPServerDialogOpen(true)
                  }}
                  hideAdd={!permissions.manage_mcp_servers}
                />
              </>
            )}

            <SessionHistory />
          </div>
        </div>
      </div>

      {/* Dialogs */}
      <ProviderDialog
        open={providerDialogOpen}
        onOpenChange={(open) => {
          setProviderDialogOpen(open)
          if (!open) setEditingProvider(null)
        }}
        provider={editingProvider}
        onUpdated={handleProviderUpdated}
      />
      <AgentDialog
        open={agentDialogOpen}
        onOpenChange={(open) => {
          setAgentDialogOpen(open)
          if (!open) setEditingAgent(null)
        }}
        agent={editingAgent}
      />
      <TeamDialog
        open={teamDialogOpen}
        onOpenChange={(open) => {
          setTeamDialogOpen(open)
          if (!open) setEditingTeam(null)
        }}
        team={editingTeam}
      />
      <ToolDialog open={toolDialogOpen} onOpenChange={setToolDialogOpen} />
      <MCPServerDialog
        open={mcpServerDialogOpen}
        onOpenChange={(open) => {
          setMCPServerDialogOpen(open)
          if (!open) setEditingMCPServer(null)
        }}
        server={editingMCPServer}
      />
    </>
  )
}
