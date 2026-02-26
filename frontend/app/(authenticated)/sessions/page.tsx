"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import { apiClient } from "@/lib/api-client"
import type { Session as ChatSession, Agent, Team, Workflow } from "@/types/playground"
import { Card, CardContent } from "@/components/ui/card"
import { AnimatedList, AnimatedListItem } from "@/components/ui/animated-list"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { History, MessageSquare, Trash2, Bot, Users, Search, GitBranch, Activity } from "lucide-react"
import { Routes } from "@/config/routes"
import { useConfirm } from "@/hooks/use-confirm"
import { TracePanel } from "@/components/ai-elements/trace-panel"

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return "Today"
  if (days === 1) return "Yesterday"
  if (days < 7) return `${days} days ago`
  return date.toLocaleDateString()
}

export default function SessionsPage() {
  const { data: authSession } = useSession()
  const router = useRouter()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [teams, setTeams] = useState<Team[]>([])
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [filterType, setFilterType] = useState("all")
  const [searchQuery, setSearchQuery] = useState("")
  const [isLoading, setIsLoading] = useState(true)
  const [traceSessionId, setTraceSessionId] = useState<string | null>(null)
  const [traceOpen, setTraceOpen] = useState(false)
  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: "Delete session",
    description: "This will permanently delete this session and all its messages. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  useEffect(() => {
    if (!authSession?.accessToken) return
    const load = async () => {
      setIsLoading(true)
      try {
        const [s, a, t, w] = await Promise.all([
          apiClient.listSessions(),
          apiClient.listAgents(),
          apiClient.listTeams(),
          apiClient.listWorkflows(),
        ])
        setSessions(s)
        setAgents(a)
        setTeams(t)
        setWorkflows(w)
      } catch (err) {
        console.error("Failed to load sessions:", err)
      }
      setIsLoading(false)
    }
    load()
  }, [authSession?.accessToken])

  // Listen for app-refresh
  useEffect(() => {
    const handleRefresh = async () => {
      try {
        const [s, a, t, w] = await Promise.all([
          apiClient.listSessions(),
          apiClient.listAgents(),
          apiClient.listTeams(),
          apiClient.listWorkflows(),
        ])
        setSessions(s)
        setAgents(a)
        setTeams(t)
        setWorkflows(w)
      } catch {}
    }
    window.addEventListener("app-refresh", handleRefresh)
    return () => window.removeEventListener("app-refresh", handleRefresh)
  }, [])

  const getEntityName = (session: ChatSession) => {
    if (session.entity_type === "agent") {
      return agents.find((a) => a.id === session.entity_id)?.name || "Unknown Agent"
    }
    if (session.entity_type === "workflow") {
      return workflows.find((w) => w.id === session.entity_id)?.name || "Unknown Workflow"
    }
    return teams.find((t) => t.id === session.entity_id)?.name || "Unknown Team"
  }

  const filteredSessions = sessions
    .filter((s) => filterType === "all" || s.entity_type === filterType)
    .filter((s) => {
      if (!searchQuery) return true
      const name = getEntityName(s).toLowerCase()
      const title = (s.title || "").toLowerCase()
      return name.includes(searchQuery.toLowerCase()) || title.includes(searchQuery.toLowerCase())
    })

  const handleOpenSession = (session: ChatSession) => {
    if (session.entity_type === "workflow") return
    router.push(
      `${Routes.PLAYGROUND}?session=${session.id}&entity_type=${session.entity_type}&entity_id=${session.entity_id}`
    )
  }

  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation()
    const ok = await confirmDelete()
    if (!ok) return
    try {
      await apiClient.deleteSession(sessionId)
      setSessions((prev) => prev.filter((s) => s.id !== sessionId))
    } catch (err) {
      console.error("Failed to delete session:", err)
    }
  }

  return (
    <div className="h-full w-full overflow-y-auto p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
          <History className="h-5 w-5 text-muted-foreground" />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight">Sessions</h1>
            <Badge variant="secondary" className="text-xs">
              {filteredSessions.length}
            </Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            View and manage your conversation history
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search sessions..."
            className="pl-9 h-9"
          />
        </div>
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-36 h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="agent">Agents</SelectItem>
            <SelectItem value="team">Teams</SelectItem>
            <SelectItem value="workflow">Workflows</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Sessions List */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            <p className="text-sm text-muted-foreground">Loading sessions...</p>
          </div>
        </div>
      ) : filteredSessions.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <MessageSquare className="h-10 w-10 text-muted-foreground/30" />
          <div>
            <p className="text-sm font-medium">No sessions found</p>
            <p className="text-xs text-muted-foreground mt-1">
              {searchQuery || filterType !== "all"
                ? "Try adjusting your filters"
                : "Start a conversation in the playground to see sessions here"}
            </p>
          </div>
        </div>
      ) : (
        <AnimatedList className="space-y-2">
          {filteredSessions.map((session) => (
            <AnimatedListItem key={session.id}>
            <Card
              className={`group transition-colors ${session.entity_type !== "workflow" ? "cursor-pointer hover:border-primary/50" : "hover:border-border"}`}
              onClick={() => handleOpenSession(session)}
            >
              <CardContent className="flex items-center gap-4 py-3 px-4">
                <div className="shrink-0">
                  {session.entity_type === "agent" ? (
                    <div className="h-8 w-8 rounded-lg bg-orange-500/10 flex items-center justify-center">
                      <Bot className="h-4 w-4 text-orange-500" />
                    </div>
                  ) : session.entity_type === "workflow" ? (
                    <div className="h-8 w-8 rounded-lg bg-emerald-500/10 flex items-center justify-center">
                      <GitBranch className="h-4 w-4 text-emerald-500" />
                    </div>
                  ) : (
                    <div className="h-8 w-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
                      <Users className="h-4 w-4 text-blue-500" />
                    </div>
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {session.title || "Untitled conversation"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-muted-foreground">
                      {getEntityName(session)}
                    </span>
                    <span className="text-xs text-muted-foreground/50">
                      {formatDate(session.created_at)}
                    </span>
                  </div>
                </div>

                <Badge
                  variant="secondary"
                  className="text-[10px] px-1.5 py-0 shrink-0"
                >
                  {session.entity_type}
                </Badge>

                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  onClick={(e) => {
                    e.stopPropagation()
                    setTraceSessionId(session.id)
                    setTraceOpen(true)
                  }}
                  title="View execution trace"
                >
                  <Activity className="h-3.5 w-3.5 text-muted-foreground" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="h-7 w-7 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  onClick={(e) => handleDeleteSession(e, session.id)}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </CardContent>
            </Card>
            </AnimatedListItem>
          ))}
        </AnimatedList>
      )}
      <ConfirmDialog />

      <TracePanel
        open={traceOpen}
        onOpenChange={setTraceOpen}
        sessionId={traceSessionId}
      />
    </div>
  )
}
