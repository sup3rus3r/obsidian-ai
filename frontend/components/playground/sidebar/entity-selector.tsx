"use client"

import { usePlaygroundStore } from "@/stores/playground-store"
import { Plus, Bot, Users, Trash2, Pencil, Download, Upload } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useState } from "react"
import { SidebarSection } from "./sidebar-section"
import { useConfirm } from "@/hooks/use-confirm"

interface EntitySelectorProps {
  onAddAgent?: () => void
  onAddTeam?: () => void
  onEditAgent?: (agentId: string) => void
  onExportAgent?: (agentId: string, agentName: string) => void
  onImportAgent?: () => void
  hideAddAgent?: boolean
  hideAddTeam?: boolean
  hideEditAgent?: boolean
  hideDeleteAgent?: boolean
  hideDeleteTeam?: boolean
}

export function EntitySelector({ onAddAgent, onAddTeam, onEditAgent, onExportAgent, onImportAgent, hideAddAgent, hideAddTeam, hideEditAgent, hideDeleteAgent, hideDeleteTeam }: EntitySelectorProps) {
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)
  const teams = usePlaygroundStore((s) => s.teams)
  const selectedAgentId = usePlaygroundStore((s) => s.selectedAgentId)
  const selectedTeamId = usePlaygroundStore((s) => s.selectedTeamId)
  const setSelectedAgent = usePlaygroundStore((s) => s.setSelectedAgent)
  const setSelectedTeam = usePlaygroundStore((s) => s.setSelectedTeam)
  const deleteAgent = usePlaygroundStore((s) => s.deleteAgent)
  const deleteTeam = usePlaygroundStore((s) => s.deleteTeam)
  const providers = usePlaygroundStore((s) => s.providers)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: `Delete ${mode}`,
    description: `This will permanently delete this ${mode}. This action cannot be undone.`,
    confirmLabel: "Delete",
    variant: "destructive",
  })

  const entities = mode === "agent" ? agents : teams
  const selectedId = mode === "agent" ? selectedAgentId : selectedTeamId
  const setSelected = mode === "agent" ? setSelectedAgent : setSelectedTeam
  const onAdd = mode === "agent" ? onAddAgent : onAddTeam
  const hideAdd = mode === "agent" ? hideAddAgent : hideAddTeam
  const onDelete = mode === "agent" ? deleteAgent : deleteTeam

  const handleDelete = async (e: React.MouseEvent, entityId: string) => {
    e.stopPropagation()
    const ok = await confirmDelete()
    if (!ok) return
    setDeletingId(entityId)
    try {
      await onDelete(entityId)
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
    <SidebarSection
      icon={mode === "agent" ? <Bot className="h-4 w-4 text-muted-foreground" /> : <Users className="h-4 w-4 text-muted-foreground" />}
      title={mode === "agent" ? "Agents" : "Teams"}
      badge={
        entities.length > 0 ? (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 min-w-4 flex items-center justify-center">
            {entities.length}
          </Badge>
        ) : undefined
      }
      action={
        !hideAdd ? (
          <div className="flex items-center gap-0.5">
            {mode === "agent" && onImportAgent && (
              <Button
                variant="ghost"
                size="icon-sm"
                className="h-6 w-6 cursor-pointer"
                onClick={onImportAgent}
                title="Import agent from JSON"
              >
                <Upload className="h-3 w-3" />
              </Button>
            )}
            <Button variant="ghost" size="icon-sm" className="h-6 w-6 cursor-pointer" onClick={onAdd}>
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
        ) : undefined
      }
    >
      {entities.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          {mode === "agent" ? (
            <Bot className="h-8 w-8 text-muted-foreground/50" />
          ) : (
            <Users className="h-8 w-8 text-muted-foreground/50" />
          )}
          <p className="text-xs text-muted-foreground">
            No {mode === "agent" ? "agents" : "teams"} yet
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {entities.map((entity) => {
            const provider =
              mode === "agent" && "provider_id" in entity
                ? providers.find((p) => p.id === entity.provider_id)
                : null
            return (
              <div
                key={entity.id}
                className={`flex items-center gap-2 px-2 py-3 rounded-md transition-colors group overflow-hidden ${
                  selectedId === entity.id
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "hover:bg-sidebar-accent/50"
                }`}
              >
                <button
                  onClick={() => setSelected(entity.id)}
                  className="flex-1 flex items-center gap-2 min-w-0 overflow-hidden uppercase"
                >
                  {mode === "agent" ? (
                    <Bot className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                  ) : (
                    <Users className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
                  )}
                  <div className="flex-1 min-w-0 text-left">
                    <div className="text-[11px] font-semibold font-medium truncate">{entity.name}</div>
                    {entity.description && (
                      <div className="text-[9px] text-muted-foreground truncate">
                        {entity.description}
                      </div>
                    )}
                  </div>
                  {(() => {
                    const modelId = ("model_id" in entity ? entity.model_id : null) || provider?.model_id
                    if (!modelId) return null
                    const label = modelId.split("/").pop()?.split("-").slice(0, 2).join("-") ?? modelId
                    return (
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 flex-shrink-0">
                        {label}
                      </Badge>
                    )
                  })()}
                </button>
                {mode === "agent" && onEditAgent && !hideEditAgent && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    onClick={(e) => {
                      e.stopPropagation()
                      onEditAgent(entity.id)
                    }}
                  >
                    <Pencil className="h-3 w-3 text-muted-foreground" />
                  </Button>
                )}
                {mode === "agent" && onExportAgent && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    onClick={(e) => {
                      e.stopPropagation()
                      onExportAgent(entity.id, entity.name)
                    }}
                    title="Export agent as JSON"
                  >
                    <Download className="h-3 w-3 text-muted-foreground" />
                  </Button>
                )}
                {!(mode === "agent" ? hideDeleteAgent : hideDeleteTeam) && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    onClick={(e) => handleDelete(e, entity.id)}
                    disabled={deletingId === entity.id}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </SidebarSection>
    <ConfirmDialog />
    </>
  )
}
