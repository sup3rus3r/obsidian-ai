"use client"

import { useEffect, useState } from "react"
import { usePlaygroundStore } from "@/stores/playground-store"
import { apiClient } from "@/lib/api-client"
import { ChevronDown, Cpu, Users, Check, Loader2 } from "lucide-react"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

export function ModelSelector() {
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)
  const setAgents = usePlaygroundStore((s) => s.setAgents)
  const selectedAgentId = usePlaygroundStore((s) => s.selectedAgentId)
  const selectedTeamId = usePlaygroundStore((s) => s.selectedTeamId)
  const teams = usePlaygroundStore((s) => s.teams)
  const providers = usePlaygroundStore((s) => s.providers)

  const selectedAgent = selectedAgentId
    ? agents.find((a) => a.id === selectedAgentId)
    : null
  const currentProvider = selectedAgent?.provider_id
    ? providers.find((p) => p.id === selectedAgent.provider_id)
    : null
  const currentModelId = selectedAgent?.model_id || currentProvider?.model_id || null

  const [models, setModels] = useState<{ id: string; name: string }[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [savingModelId, setSavingModelId] = useState<string | null>(null)

  useEffect(() => {
    if (mode === "team" || !currentProvider) {
      setModels([])
      return
    }
    setLoadingModels(true)
    apiClient
      .listModels(currentProvider.id)
      .then(setModels)
      .catch(() => setModels([]))
      .finally(() => setLoadingModels(false))
  }, [mode, currentProvider?.id])

  const getModelLabel = (modelId: string | null | undefined) => {
    if (!modelId) return "No model"
    const parts = modelId.split("/")
    return parts[parts.length - 1]
  }

  // --- Team mode: show team agents and their models (read-only) ---
  if (mode === "team") {
    const selectedTeam = selectedTeamId
      ? teams.find((t) => t.id === selectedTeamId)
      : null

    if (!selectedTeam) return null

    const teamAgents = agents.filter((a) => selectedTeam.agent_ids.includes(a.id))
    const teamAgentModels = teamAgents.map((ag) => {
      const pr = ag.provider_id ? providers.find((p) => p.id === ag.provider_id) : null
      return { agent: ag, provider: pr }
    })

    const modeLabels = {
      coordinate: "Coordinate",
      route: "Route",
      collaborate: "Collaborate",
    }

    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className="flex items-center gap-1.5 text-xs bg-muted hover:bg-muted/80 px-2.5 py-1 rounded-md text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
            <Users className="h-3 w-3" />
            <span className="max-w-[150px] truncate">
              {modeLabels[selectedTeam.mode]} · {teamAgents.length} agents
            </span>
            <ChevronDown className="h-3 w-3 opacity-50" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
            Team Agents & Models
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          {teamAgentModels.map(({ agent, provider }) => (
            <div
              key={agent.id}
              className="flex items-center justify-between px-2 py-1.5"
            >
              <span className="text-xs font-medium">{agent.name}</span>
              <span className="text-[10px] text-muted-foreground font-mono">
                {getModelLabel(agent.model_id || provider?.model_id)}
              </span>
            </div>
          ))}
          {teamAgentModels.length === 0 && (
            <div className="px-2 py-3 text-center">
              <p className="text-xs text-muted-foreground">No agents in team</p>
            </div>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  // --- Agent mode: switchable model ---
  if (!selectedAgent) return null

  const handleSelectModel = async (modelId: string) => {
    if (!selectedAgent || modelId === currentModelId) return
    setSavingModelId(modelId)
    try {
      const updated = await apiClient.updateAgent(selectedAgent.id, {
        model_id: modelId,
      })
      setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
    } catch (err) {
      console.error("Failed to update agent model:", err)
    } finally {
      setSavingModelId(null)
    }
  }

  const handleSelectProvider = async (providerId: string) => {
    if (!selectedAgent || providerId === selectedAgent.provider_id) return
    try {
      const updated = await apiClient.updateAgent(selectedAgent.id, {
        provider_id: providerId,
      })
      setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
    } catch (err) {
      console.error("Failed to update agent provider:", err)
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-1.5 text-xs bg-muted hover:bg-muted/80 px-2.5 py-1 rounded-md text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          <Cpu className="h-3 w-3" />
          <span className="max-w-[150px] truncate">
            {getModelLabel(currentModelId)}
          </span>
          <ChevronDown className="h-3 w-3 opacity-50" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Switch Model
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {loadingModels && (
          <div className="px-2 py-3 flex items-center justify-center gap-1.5 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="text-xs">Loading models...</span>
          </div>
        )}
        {!loadingModels &&
          models.map((model) => (
            <DropdownMenuItem
              key={model.id}
              onClick={() => handleSelectModel(model.id)}
              className={cn(
                "flex items-center justify-between gap-2 cursor-pointer",
                model.id === currentModelId && "bg-accent"
              )}
            >
              <span className="text-xs font-mono truncate">{model.name || getModelLabel(model.id)}</span>
              {savingModelId === model.id ? (
                <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
              ) : model.id === currentModelId ? (
                <Check className="h-3 w-3 shrink-0" />
              ) : null}
            </DropdownMenuItem>
          ))}
        {!loadingModels && models.length === 0 && (
          <div className="px-2 py-3 text-center">
            <p className="text-xs text-muted-foreground">No models available for this provider</p>
          </div>
        )}
        {providers.length > 1 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
              Switch Provider
            </DropdownMenuLabel>
            {providers.map((provider) => (
              <DropdownMenuItem
                key={provider.id}
                onClick={() => handleSelectProvider(provider.id)}
                className={cn(
                  "flex flex-col items-start gap-0.5 cursor-pointer",
                  provider.id === selectedAgent.provider_id && "bg-accent"
                )}
              >
                <span className="text-xs font-medium">{provider.name}</span>
                <span className="text-[10px] text-muted-foreground font-mono">
                  {provider.provider_type}
                </span>
              </DropdownMenuItem>
            ))}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
