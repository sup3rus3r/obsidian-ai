"use client"

import { useEffect } from "react"
import { useSession } from "next-auth/react"
import { usePlaygroundStore } from "@/stores/playground-store"
import { apiClient } from "@/lib/api-client"
import { MessageSquare, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { SidebarSection } from "./sidebar-section"

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return `${days} days ago`
  return date.toLocaleDateString()
}

function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function SessionHistory() {
  const { data: authSession } = useSession()
  const mode = usePlaygroundStore((s) => s.mode)
  const selectedAgentId = usePlaygroundStore((s) => s.selectedAgentId)
  const selectedTeamId = usePlaygroundStore((s) => s.selectedTeamId)
  const sessions = usePlaygroundStore((s) => s.sessions)
  const setSessions = usePlaygroundStore((s) => s.setSessions)
  const selectedSessionId = usePlaygroundStore((s) => s.selectedSessionId)
  const setSelectedSession = usePlaygroundStore((s) => s.setSelectedSession)
  const fetchSessionMessages = usePlaygroundStore((s) => s.fetchSessionMessages)
  const deleteSession = usePlaygroundStore((s) => s.deleteSession)

  const entityId = mode === "agent" ? selectedAgentId : selectedTeamId

  useEffect(() => {
    if (!authSession?.accessToken || !entityId) {
      setSessions([])
      return
    }

    const load = async () => {
      try {
        const filtered = await apiClient.listSessionsFiltered(mode, entityId)
        setSessions(filtered)
      } catch (err) {
        console.error("Failed to load sessions:", err)
      }
    }

    load()
  }, [authSession?.accessToken, mode, entityId, setSessions])

  const loadSession = async (sessionId: string) => {
    setSelectedSession(sessionId)
    try {
      await fetchSessionMessages(sessionId)
    } catch (err) {
      console.error("Failed to load messages:", err)
    }
  }

  return (
    <SidebarSection
      icon={<MessageSquare className="h-4 w-4 text-muted-foreground" />}
      title="Sessions"
      badge={
        sessions.length > 0 ? (
          <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 min-w-4 flex items-center justify-center">
            {sessions.length}
          </Badge>
        ) : undefined
      }
    >
      {!entityId ? (
        <p className="text-xs text-muted-foreground">
          Select an {mode} to see sessions
        </p>
      ) : sessions.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <MessageSquare className="h-6 w-6 text-muted-foreground/50" />
          <p className="text-xs text-muted-foreground">No conversations yet</p>
        </div>
      ) : (
        <div className="space-y-1">
          {sessions.map((session) => (
            <div
              key={session.id}
              onClick={() => loadSession(session.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === "Enter") loadSession(session.id) }}
              className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left group transition-colors cursor-pointer overflow-hidden h-16 ${
                selectedSessionId === session.id
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "hover:bg-sidebar-accent/50"
              }`}
            >
              <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <div className="flex-1 min-w-0 overflow-hidden">
                <div className="text-sm truncate">
                  {session.title || "New conversation"}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {formatRelativeDate(session.created_at)}
                </div>
                {((session.total_input_tokens ?? 0) + (session.total_output_tokens ?? 0)) > 0 && (
                  <div className="text-[10px] text-muted-foreground/70 tabular-nums">
                    {formatTokenCount((session.total_input_tokens ?? 0) + (session.total_output_tokens ?? 0))} tokens
                  </div>
                )}
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  deleteSession(session.id)
                }}
                className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-sidebar-accent"
              >
                <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground transition-colors" />
              </button>
            </div>
          ))}
        </div>
      )}
    </SidebarSection>
  )
}
