"use client"

import { usePlaygroundStore } from "@/stores/playground-store"
import { apiClient } from "@/lib/api-client"
import { ChevronDown, Cpu, Users } from "lucide-react"
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

  const getModelLabel = (modelId: string) => {
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
                {provider ? getModelLabel(provider.model_id) : "No model"}
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

  // --- Agent mode: switchable provider ---
  const selectedAgent = selectedAgentId
    ? agents.find((a) => a.id === selectedAgentId)
    : null

  const currentProvider = selectedAgent?.provider_id
    ? providers.find((p) => p.id === selectedAgent.provider_id)
    : null

  if (!selectedAgent) return null

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
            {currentProvider ? getModelLabel(currentProvider.model_id) : "No model"}
          </span>
          <ChevronDown className="h-3 w-3 opacity-50" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="text-[10px] uppercase tracking-wider text-muted-foreground">
          Switch Model
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
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
              {provider.model_id}
            </span>
          </DropdownMenuItem>
        ))}
        {providers.length === 0 && (
          <div className="px-2 py-3 text-center">
            <p className="text-xs text-muted-foreground">No providers configured</p>
          </div>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
