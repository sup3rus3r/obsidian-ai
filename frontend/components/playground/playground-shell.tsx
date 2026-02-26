"use client"

import { useEffect } from "react"
import { useSession } from "next-auth/react"
import { useSearchParams } from "next/navigation"
import { Sidebar } from "./sidebar/sidebar"
import { ModelSelector } from "./model-selector"
import { ArtifactPanel } from "./artifact-panel"
import { usePlaygroundStore } from "@/stores/playground-store"
import { PanelLeftClose, PanelLeft, SquarePen, PanelRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export function PlaygroundShell({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession()
  const searchParams = useSearchParams()
  const sidebarOpen = usePlaygroundStore((s) => s.sidebarOpen)
  const toggleSidebar = usePlaygroundStore((s) => s.toggleSidebar)
  const fetchProviders = usePlaygroundStore((s) => s.fetchProviders)
  const fetchAgents = usePlaygroundStore((s) => s.fetchAgents)
  const fetchTeams = usePlaygroundStore((s) => s.fetchTeams)
  const setSelectedAgent = usePlaygroundStore((s) => s.setSelectedAgent)
  const setSelectedTeam = usePlaygroundStore((s) => s.setSelectedTeam)
  const setMode = usePlaygroundStore((s) => s.setMode)
  const setSelectedSession = usePlaygroundStore((s) => s.setSelectedSession)
  const fetchSessionMessages = usePlaygroundStore((s) => s.fetchSessionMessages)

  // Load data when authenticated
  useEffect(() => {
    if (status !== "authenticated" || !session?.accessToken) return

    const load = async () => {
      try {
        await Promise.all([
          fetchProviders(),
          fetchAgents(),
          fetchTeams(),
        ])
      } catch (err) {
        console.error("Failed to load playground data:", err)
      }
    }

    load()
  }, [status, session?.accessToken, fetchProviders, fetchAgents, fetchTeams])

  // Handle URL params for deep linking
  useEffect(() => {
    if (status !== "authenticated") return

    const agentId = searchParams.get("agent")
    const teamId = searchParams.get("team")
    const sessionId = searchParams.get("session")
    const entityType = searchParams.get("entity_type")
    const entityId = searchParams.get("entity_id")

    if (sessionId && entityType && entityId) {
      setMode(entityType as "agent" | "team")
      if (entityType === "agent") {
        setSelectedAgent(entityId)
      } else {
        setSelectedTeam(entityId)
      }
      setSelectedSession(sessionId)
      fetchSessionMessages(sessionId)
    } else if (agentId) {
      setMode("agent")
      setSelectedAgent(agentId)
    } else if (teamId) {
      setMode("team")
      setSelectedTeam(teamId)
    }
  }, [status, searchParams, setMode, setSelectedAgent, setSelectedTeam, setSelectedSession, fetchSessionMessages])

  // Listen for app-refresh events
  useEffect(() => {
    const handleRefresh = () => {
      fetchProviders()
      fetchAgents()
      fetchTeams()
    }
    window.addEventListener("app-refresh", handleRefresh)
    return () => window.removeEventListener("app-refresh", handleRefresh)
  }, [fetchProviders, fetchAgents, fetchTeams])

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <div
        className={`${
          sidebarOpen ? "w-88" : "w-0"
        } shrink-0 transition-all duration-200 overflow-hidden border-r border-border`}
      >
        <Sidebar />
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {/* Top bar */}
        <div className="flex items-center h-12 px-4 border-b border-border gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={toggleSidebar}
            className="shrink-0"
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-4 w-4" />
            ) : (
              <PanelLeft className="h-4 w-4" />
            )}
          </Button>
          <TopBar />
        </div>

        {/* Chat + Artifact split */}
        <div className="flex-1 min-h-0 flex overflow-hidden">
          <div className="flex-1 min-w-0 relative">
            <div className="absolute inset-0 flex flex-col">
              {children}
            </div>
          </div>
          <ArtifactPanel />
        </div>
      </div>
    </div>
  )
}

function TopBar() {
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)
  const teams = usePlaygroundStore((s) => s.teams)
  const selectedAgentId = usePlaygroundStore((s) => s.selectedAgentId)
  const selectedTeamId = usePlaygroundStore((s) => s.selectedTeamId)
  const clearChat = usePlaygroundStore((s) => s.clearChat)
  const isStreaming = usePlaygroundStore((s) => s.isStreaming)
  const artifacts = usePlaygroundStore((s) => s.artifacts)
  const streamingArtifact = usePlaygroundStore((s) => s.streamingArtifact)
  const artifactPanelOpen = usePlaygroundStore((s) => s.artifactPanelOpen)
  const setArtifactPanelOpen = usePlaygroundStore((s) => s.setArtifactPanelOpen)

  const selectedEntity =
    mode === "agent"
      ? agents.find((a) => a.id === selectedAgentId)
      : teams.find((t) => t.id === selectedTeamId)

  return (
    <div className="flex items-center gap-3 flex-1">
      {selectedEntity ? (
        <>
          <span className="text-sm font-medium">{selectedEntity.name}</span>
          <ModelSelector />
          <div className="ml-auto flex items-center gap-1">
            {(artifacts.length > 0 || !!streamingArtifact) && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant={artifactPanelOpen ? "secondary" : "ghost"}
                      size="icon-sm"
                      onClick={() => setArtifactPanelOpen(!artifactPanelOpen)}
                    >
                      <PanelRight className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{artifactPanelOpen ? "Hide artifacts" : streamingArtifact ? "Show artifact (writing…)" : `Show artifacts (${artifacts.length})`}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    onClick={clearChat}
                    disabled={isStreaming}
                  >
                    <SquarePen className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>New chat</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </>
      ) : (
        <span className="text-sm text-muted-foreground">
          Select an agent to start chatting
        </span>
      )}
    </div>
  )
}
