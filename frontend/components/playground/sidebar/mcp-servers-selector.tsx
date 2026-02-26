"use client"

import { useEffect } from "react"
import { usePlaygroundStore } from "@/stores/playground-store"
import { apiClient } from "@/lib/api-client"
import { Server, CheckCircle2, Circle, Plus, Trash2, Plug, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useState } from "react"
import { SidebarSection } from "./sidebar-section"
import { useConfirm } from "@/hooks/use-confirm"

interface MCPServersSelectorProps {
  onAddServer?: () => void
  onEditServer?: (server: import("@/types/playground").MCPServer) => void
  hideAdd?: boolean
}

export function MCPServersSelector({ onAddServer, onEditServer, hideAdd }: MCPServersSelectorProps) {
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)
  const teams = usePlaygroundStore((s) => s.teams)
  const setAgents = usePlaygroundStore((s) => s.setAgents)
  const selectedAgentId = usePlaygroundStore((s) => s.selectedAgentId)
  const selectedTeamId = usePlaygroundStore((s) => s.selectedTeamId)
  const mcpServers = usePlaygroundStore((s) => s.mcpServers)
  const fetchMCPServers = usePlaygroundStore((s) => s.fetchMCPServers)
  const deleteMCPServer = usePlaygroundStore((s) => s.deleteMCPServer)

  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({})
  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: "Delete MCP server",
    description: "This will permanently delete this MCP server configuration. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  const selectedAgent =
    mode === "agent" && selectedAgentId
      ? agents.find((a) => a.id === selectedAgentId)
      : null

  const selectedTeam =
    mode === "team" && selectedTeamId
      ? teams.find((t) => t.id === selectedTeamId)
      : null

  const agentMCPServerIds = selectedAgent?.mcp_server_ids || []

  useEffect(() => {
    fetchMCPServers()
  }, [])

  // Refresh when a server is created
  useEffect(() => {
    const handler = () => fetchMCPServers()
    window.addEventListener("mcp-server-created", handler)
    return () => window.removeEventListener("mcp-server-created", handler)
  }, [])

  const toggleServer = async (serverId: string) => {
    if (!selectedAgent || saving) return
    setSaving(true)
    const newIds = agentMCPServerIds.includes(serverId)
      ? agentMCPServerIds.filter((id) => id !== serverId)
      : [...agentMCPServerIds, serverId]
    try {
      const updated = await apiClient.updateAgent(selectedAgent.id, { mcp_server_ids: newIds })
      setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
    } catch (err) {
      console.error("Failed to update agent MCP servers:", err)
    } finally {
      setSaving(false)
    }
  }

  const handleEdit = (e: React.MouseEvent, server: import("@/types/playground").MCPServer) => {
    e.stopPropagation()
    onEditServer?.(server)
  }

  const handleTest = async (e: React.MouseEvent, serverId: string) => {
    e.stopPropagation()
    setTestingId(serverId)
    setTestResults((prev) => ({ ...prev, [serverId]: undefined as any }))
    try {
      const result = await apiClient.testMCPServer(serverId)
      if (result.success) {
        setTestResults((prev) => ({
          ...prev,
          [serverId]: { success: true, message: `${result.tools_count} tool(s) found` },
        }))
      } else {
        setTestResults((prev) => ({
          ...prev,
          [serverId]: { success: false, message: result.error || "Connection failed" },
        }))
      }
    } catch {
      setTestResults((prev) => ({
        ...prev,
        [serverId]: { success: false, message: "Failed to test connection" },
      }))
    } finally {
      setTestingId(null)
    }
  }

  const handleDelete = async (e: React.MouseEvent, serverId: string) => {
    e.stopPropagation()
    const ok = await confirmDelete()
    if (!ok) return
    try {
      await deleteMCPServer(serverId)
    } catch (err) {
      console.error("Failed to delete MCP server:", err)
    }
  }

  const activeCount = mcpServers.filter((s) => agentMCPServerIds.includes(s.id)).length

  return (
    <>
    <SidebarSection
      icon={<Server className="h-4 w-4 text-muted-foreground" />}
      title="MCP Servers"
      badge={
        activeCount > 0 ? (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 min-w-4 flex items-center justify-center">
            {activeCount}
          </Badge>
        ) : undefined
      }
      action={
        !hideAdd ? (
          <Button variant="ghost" size="icon-sm" className="h-6 w-6 cursor-pointer" onClick={onAddServer}>
            <Plus className="h-3.5 w-3.5" />
          </Button>
        ) : undefined
      }
    >
      {!selectedAgent && !selectedTeam ? (
        <p className="text-xs text-muted-foreground">
          Select an {mode} to configure MCP servers
        </p>
      ) : mode === "team" && selectedTeam ? (
        <p className="text-xs text-muted-foreground">
          Configure MCP servers on individual agents
        </p>
      ) : selectedAgent ? (
        <div className="space-y-2">
          {mcpServers.length === 0 ? (
            <div className="text-center py-3">
              <p className="text-xs text-muted-foreground mb-2">
                No MCP servers configured yet
              </p>
              {!hideAdd && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-9 w-full cursor-pointer text-xs"
                  onClick={onAddServer}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add MCP Server
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {mcpServers.map((server) => {
                const isEnabled = agentMCPServerIds.includes(server.id)
                return (
                  <div key={server.id}>
                    <div
                      onClick={() => toggleServer(server.id)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") toggleServer(server.id) }}
                      className={`flex items-start gap-3 p-1.5 py-3 rounded text-xs cursor-pointer transition-colors group ${
                        saving ? "opacity-50 pointer-events-none" : "hover:bg-sidebar-accent/30"
                      }`}
                    >
                      <div className="pt-0.5">
                        {isEnabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{server.name}</div>
                        {server.description && (
                          <div className="text-muted-foreground truncate">
                            {server.description}
                          </div>
                        )}
                        <div className="text-muted-foreground/60 mt-0.5">
                          {server.transport_type === "stdio" ? "stdio" : "sse"}{" "}
                          {server.transport_type === "stdio"
                            ? `· ${server.command || ""}`
                            : `· ${server.url || ""}`}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity pt-0.5">
                        <button
                          onClick={(e) => handleEdit(e, server)}
                          title="Edit server"
                        >
                          <Pencil className="h-3 w-3 text-muted-foreground hover:text-foreground transition-colors" />
                        </button>
                        <button
                          onClick={(e) => handleTest(e, server.id)}
                          disabled={testingId === server.id}
                          title="Test connection"
                          className="disabled:opacity-50"
                        >
                          {testingId === server.id ? (
                            <Loader2 className="h-3 w-3 text-muted-foreground animate-spin" />
                          ) : (
                            <Plug className="h-3 w-3 text-muted-foreground hover:text-foreground transition-colors" />
                          )}
                        </button>
                        <button
                          onClick={(e) => handleDelete(e, server.id)}
                        >
                          <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive transition-colors" />
                        </button>
                      </div>
                    </div>
                    {testResults[server.id] && (
                      <div
                        className={`ml-7 mb-1 px-2 py-1 rounded text-[10px] ${
                          testResults[server.id].success
                            ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                            : "bg-destructive/10 text-destructive"
                        }`}
                      >
                        {testResults[server.id].success ? (
                          <CheckCircle2 className="h-3 w-3 inline mr-1" />
                        ) : null}
                        {testResults[server.id].message}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      ) : null}
    </SidebarSection>
    <ConfirmDialog />
    </>
  )
}
