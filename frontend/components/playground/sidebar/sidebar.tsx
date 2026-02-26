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
import type { Agent, MCPServer } from "@/types/playground"

export function Sidebar() {
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)
  const setAgents = usePlaygroundStore((s) => s.setAgents)
  const setSelectedAgent = usePlaygroundStore((s) => s.setSelectedAgent)
  const permissions = usePermissionsStore((s) => s.permissions)
  const [providerDialogOpen, setProviderDialogOpen] = useState(false)
  const [agentDialogOpen, setAgentDialogOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [teamDialogOpen, setTeamDialogOpen] = useState(false)
  const [toolDialogOpen, setToolDialogOpen] = useState(false)
  const [mcpServerDialogOpen, setMCPServerDialogOpen] = useState(false)
  const [editingMCPServer, setEditingMCPServer] = useState<MCPServer | null>(null)
  const importInputRef = useRef<HTMLInputElement>(null)

  const handleEditAgent = (agentId: string) => {
    const agent = agents.find((a) => a.id === agentId)
    if (agent) {
      setEditingAgent(agent)
      setAgentDialogOpen(true)
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

      <div className="flex flex-col h-full w-88 min-w-0 bg-sidebar text-sidebar-foreground overflow-hidden">
        {/* Header */}
        <div className="flex items-center h-12 px-4 border-b border-sidebar-border">
          <h1 className="text-sm font-semibold tracking-tight">Obsidian AI</h1>
        </div>

        <div className="flex-1 overflow-y-auto overflow-x-hidden">
          <div className="flex flex-col gap-4 p-3">
            <EndpointConfig
              onAddProvider={() => setProviderDialogOpen(true)}
              hideAdd={!permissions.manage_providers}
            />
            <ModeToggle />
            <EntitySelector
              onAddAgent={() => setAgentDialogOpen(true)}
              onAddTeam={() => setTeamDialogOpen(true)}
              onEditAgent={handleEditAgent}
              onExportAgent={handleExportAgent}
              onImportAgent={permissions.create_agents ? handleImportAgent : undefined}
              hideAddAgent={!permissions.create_agents}
              hideAddTeam={!permissions.create_teams}
              hideEditAgent={!permissions.create_agents}
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
      <ProviderDialog open={providerDialogOpen} onOpenChange={setProviderDialogOpen} />
      <AgentDialog
        open={agentDialogOpen}
        onOpenChange={(open) => {
          setAgentDialogOpen(open)
          if (!open) setEditingAgent(null)
        }}
        agent={editingAgent}
      />
      <TeamDialog open={teamDialogOpen} onOpenChange={setTeamDialogOpen} />
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
