"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useDashboardStore } from "@/stores/dashboard-store"
import { usePlaygroundStore } from "@/stores/playground-store"
import { usePermissionsStore } from "@/stores/permissions-store"
import { apiClient } from "@/lib/api-client"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { AnimatedList, AnimatedListItem } from "@/components/ui/animated-list"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { AgentDialog } from "@/components/playground/dialogs/agent-dialog"
import { TeamDialog } from "@/components/playground/dialogs/team-dialog"
import { WorkflowDialog } from "@/components/dialogs/workflow-dialog"
import { WorkflowRunDialog } from "@/components/dialogs/workflow-run-dialog"
import { WorkflowHistoryDialog } from "@/components/dialogs/workflow-history-dialog"
import { WorkflowScheduleDialog } from "@/components/dialogs/workflow-schedule-dialog"
import { WorkflowStepsView } from "@/components/playground/workflow-steps-view"
import { Routes } from "@/config/routes"
import { useConfirm } from "@/hooks/use-confirm"
import type { Agent, Workflow } from "@/types/playground"
import {
  MessageSquare,
  History,
  Bot,
  Users,
  GitBranch,
  Settings,
  ArrowUpRight,
  Plus,
  ChevronDown,
  ChevronRight,
  Trash2,
} from "lucide-react"

const exploreCards = [
  {
    title: "Chat",
    description: "Interact with your agents, teams and workflows.",
    icon: MessageSquare,
    href: Routes.PLAYGROUND,
  },
  {
    title: "Sessions",
    description: "View and manage your conversation history.",
    icon: History,
    href: Routes.SESSIONS,
  },
  {
    title: "Settings",
    description: "Configure application preferences.",
    icon: Settings,
    href: Routes.SETTINGS,
  },
]

export default function HomePage() {
  const { data: session } = useSession()
  const router = useRouter()
  const {
    agents,
    teams,
    workflows,
    isLoading,
    fetchAll,
    deleteAgent,
    deleteTeam,
    deleteWorkflow,
  } = useDashboardStore()

  const playgroundProviders = usePlaygroundStore((s) => s.providers)
  const fetchProviders = usePlaygroundStore((s) => s.fetchProviders)
  const permissions = usePermissionsStore((s) => s.permissions)

  const [agentDialogOpen, setAgentDialogOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null)
  const [teamDialogOpen, setTeamDialogOpen] = useState(false)
  const [workflowDialogOpen, setWorkflowDialogOpen] = useState(false)
  const [editingWorkflow, setEditingWorkflow] = useState<Workflow | null>(null)
  const [workflowRunDialogOpen, setWorkflowRunDialogOpen] = useState(false)
  const [workflowHistoryDialogOpen, setWorkflowHistoryDialogOpen] = useState(false)
  const [workflowScheduleDialogOpen, setWorkflowScheduleDialogOpen] = useState(false)
  const [selectedWorkflow, setSelectedWorkflow] = useState<Workflow | null>(null)

  const [agentsOpen, setAgentsOpen] = useState(true)
  const [teamsOpen, setTeamsOpen] = useState(true)
  const [workflowsOpen, setWorkflowsOpen] = useState(true)

  const [ConfirmDeleteAgent, confirmDeleteAgent] = useConfirm({
    title: "Delete agent",
    description: "This will permanently delete this agent. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })
  const [ConfirmDeleteTeam, confirmDeleteTeam] = useConfirm({
    title: "Delete team",
    description: "This will permanently delete this team. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })
  const [ConfirmDeleteWorkflow, confirmDeleteWorkflow] = useConfirm({
    title: "Delete workflow",
    description: "This will permanently delete this workflow. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  useEffect(() => {
    if (!session?.accessToken) return
    fetchAll()
    fetchProviders()
  }, [session?.accessToken, fetchAll, fetchProviders])

  useEffect(() => {
    const handleRefresh = () => {
      fetchAll()
      fetchProviders()
    }
    window.addEventListener("app-refresh", handleRefresh)
    return () => window.removeEventListener("app-refresh", handleRefresh)
  }, [fetchAll, fetchProviders])

  const navigateToChat = (entityType: "agent" | "team", entityId: string) => {
    router.push(`${Routes.PLAYGROUND}?${entityType}=${entityId}`)
  }

  const handleDeleteAgent = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    const ok = await confirmDeleteAgent()
    if (!ok) return
    try { await deleteAgent(id) } catch {}
  }

  const handleDeleteTeam = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    const ok = await confirmDeleteTeam()
    if (!ok) return
    try { await deleteTeam(id) } catch {}
  }

  const handleDeleteWorkflow = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    const ok = await confirmDeleteWorkflow()
    if (!ok) return
    try { await deleteWorkflow(id) } catch {}
  }

  const getProviderLabel = (providerId?: string) => {
    if (!providerId) return null
    const p = playgroundProviders.find((prov) => prov.id === providerId)
    return p?.model_id ? p.model_id.split("/").pop()?.split("-").slice(0, 2).join("-") : null
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-6 w-full max-w-6xl mx-auto space-y-8">
      {/* Welcome */}
      <h1 className="text-2xl font-bold tracking-tight uppercase">
        Welcome {session?.user?.name || "back"}
      </h1>

      {/* Explore */}
      <section>
        <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
          Explore
        </h2>
        <AnimatedList className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {exploreCards.map((card) => (
            <AnimatedListItem key={card.title}>
              <Link href={card.href}>
                <Card className="group cursor-pointer hover:border-primary/50 transition-colors h-full">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <card.icon className="h-4 w-4 text-muted-foreground" />
                        <CardTitle className="text-sm">{card.title}</CardTitle>
                      </div>
                      <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="text-xs text-muted-foreground">{card.description}</p>
                  </CardContent>
                </Card>
              </Link>
            </AnimatedListItem>
          ))}
        </AnimatedList>
      </section>

      {/* Agents */}
      <section>
        <button
          onClick={() => setAgentsOpen(!agentsOpen)}
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3 hover:text-foreground transition-colors"
        >
          {agentsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Agents
          {agents.length > 0 && (
            <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">
              {agents.length}
            </Badge>
          )}
        </button>
        {agentsOpen && (
          <AnimatedList className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <AnimatedListItem key={agent.id}>
              <Card className="group hover:border-primary/50 transition-colors">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="h-7 w-7 rounded-lg bg-orange-500/10 flex items-center justify-center shrink-0">
                        <Bot className="h-3.5 w-3.5 text-orange-500" />
                      </div>
                      <CardTitle className="text-sm font-mono">{agent.name.toUpperCase()}</CardTitle>
                    </div>
                    {permissions.create_agents && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => handleDeleteAgent(e, agent.id)}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    )}
                  </div>
                  {agent.description && (
                    <CardDescription className="text-xs line-clamp-1 mt-1">
                      {agent.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs font-mono"
                      onClick={() => navigateToChat("agent", agent.id)}
                    >
                      CHAT
                    </Button>
                    {permissions.create_agents && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs font-mono"
                        onClick={() => {
                          setEditingAgent(agent)
                          setAgentDialogOpen(true)
                        }}
                      >
                        CONFIG
                      </Button>
                    )}
                    {getProviderLabel(agent.provider_id) && (
                      <Badge variant="secondary" className="ml-auto text-[10px] px-1.5 py-0">
                        {getProviderLabel(agent.provider_id)}
                      </Badge>
                    )}
                  </div>
                </CardContent>
              </Card>
              </AnimatedListItem>
            ))}
            {permissions.create_agents && (
              <AnimatedListItem>
                <Card
                  className="border-dashed cursor-pointer hover:border-primary/50 transition-colors flex items-center justify-center min-h-30"
                  onClick={() => setAgentDialogOpen(true)}
                >
                  <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                    <Plus className="h-5 w-5" />
                    <span className="text-xs">Create Agent</span>
                  </div>
                </Card>
              </AnimatedListItem>
            )}
          </AnimatedList>
        )}
      </section>

      {/* Teams */}
      <section>
        <button
          onClick={() => setTeamsOpen(!teamsOpen)}
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3 hover:text-foreground transition-colors"
        >
          {teamsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Teams
          {teams.length > 0 && (
            <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">
              {teams.length}
            </Badge>
          )}
        </button>
        {teamsOpen && (
          <AnimatedList className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {teams.map((team) => (
              <AnimatedListItem key={team.id}>
              <Card className="group hover:border-primary/50 transition-colors">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="h-7 w-7 rounded-lg bg-blue-500/10 flex items-center justify-center shrink-0">
                        <Users className="h-3.5 w-3.5 text-blue-500" />
                      </div>
                      <CardTitle className="text-sm font-mono">{team.name.toUpperCase()}</CardTitle>
                    </div>
                    {permissions.create_teams && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => handleDeleteTeam(e, team.id)}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    )}
                  </div>
                  {team.description && (
                    <CardDescription className="text-xs line-clamp-1 mt-1">
                      {team.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs font-mono"
                      onClick={() => navigateToChat("team", team.id)}
                    >
                      CHAT
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs font-mono"
                      onClick={() => navigateToChat("team", team.id)}
                    >
                      CONFIG
                    </Button>
                    <Badge variant="secondary" className="ml-auto text-[10px] px-1.5 py-0">
                      {team.mode}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
              </AnimatedListItem>
            ))}
            {permissions.create_teams && (
            <AnimatedListItem>
              <Card
                className="border-dashed flex items-center justify-center min-h-30 transition-colors cursor-pointer hover:border-primary/50"
                onClick={() => setTeamDialogOpen(true)}
              >
                <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                  <Plus className="h-5 w-5" />
                  <span className="text-xs">Create Team</span>
                </div>
              </Card>
            </AnimatedListItem>
            )}
          </AnimatedList>
        )}
      </section>

      {/* Workflows */}
      <section>
        <button
          onClick={() => setWorkflowsOpen(!workflowsOpen)}
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3 hover:text-foreground transition-colors"
        >
          {workflowsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          Workflows
          {workflows.length > 0 && (
            <Badge variant="secondary" className="ml-1 text-[10px] px-1.5 py-0">
              {workflows.length}
            </Badge>
          )}
        </button>
        {workflowsOpen && (
          <AnimatedList className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {workflows.map((workflow) => (
              <AnimatedListItem key={workflow.id}>
              <Card className="group hover:border-primary/50 transition-colors">
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="h-7 w-7 rounded-lg bg-emerald-500/10 flex items-center justify-center shrink-0">
                        <GitBranch className="h-3.5 w-3.5 text-emerald-500" />
                      </div>
                      <CardTitle className="text-sm font-mono">{workflow.name.toUpperCase()}</CardTitle>
                    </div>
                    {permissions.create_workflows && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity"
                        onClick={(e) => handleDeleteWorkflow(e, workflow.id)}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    )}
                  </div>
                  {workflow.description && (
                    <CardDescription className="text-xs line-clamp-1 mt-1">
                      {workflow.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="pt-0 space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs font-mono"
                      onClick={() => {
                        setSelectedWorkflow(workflow)
                        setWorkflowRunDialogOpen(true)
                      }}
                    >
                      RUN
                    </Button>
                    {permissions.create_workflows && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs font-mono"
                        onClick={() => {
                          setEditingWorkflow(workflow)
                          setWorkflowDialogOpen(true)
                        }}
                      >
                        EDIT
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs font-mono"
                      onClick={() => {
                        setSelectedWorkflow(workflow)
                        setWorkflowHistoryDialogOpen(true)
                      }}
                    >
                      HISTORY
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs font-mono"
                      onClick={() => {
                        setSelectedWorkflow(workflow)
                        setWorkflowScheduleDialogOpen(true)
                      }}
                    >
                      SCHEDULE
                    </Button>
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                      {workflow.steps.length} step{workflow.steps.length !== 1 ? "s" : ""}
                    </Badge>
                  </div>
                  {workflow.steps.length > 0 && (
                    <WorkflowStepsView
                      steps={workflow.steps}
                      agents={agents}
                      defaultOpen={false}
                      title="View pipeline"
                    />
                  )}
                </CardContent>
              </Card>
              </AnimatedListItem>
            ))}
            {permissions.create_workflows && (
            <AnimatedListItem>
              <Card
                className="border-dashed flex items-center justify-center min-h-30 transition-colors cursor-pointer hover:border-primary/50"
                onClick={() => { setEditingWorkflow(null); setWorkflowDialogOpen(true) }}
              >
                <div className="flex flex-col items-center gap-1.5 text-muted-foreground">
                  <Plus className="h-5 w-5" />
                  <span className="text-xs">Create Workflow</span>
                </div>
              </Card>
            </AnimatedListItem>
            )}
          </AnimatedList>
        )}
      </section>

      {/* Dialogs */}
      <AgentDialog
        open={agentDialogOpen}
        onOpenChange={(open) => {
          setAgentDialogOpen(open)
          if (!open) setEditingAgent(null)
        }}
        agent={editingAgent}
        onSaved={() => fetchAll()}
      />
      <TeamDialog open={teamDialogOpen} onOpenChange={setTeamDialogOpen} />
      <WorkflowDialog
        open={workflowDialogOpen}
        onOpenChange={(open) => {
          setWorkflowDialogOpen(open)
          if (!open) setEditingWorkflow(null)
        }}
        workflow={editingWorkflow}
        agents={agents}
        onCreated={() => fetchAll()}
        onUpdated={() => fetchAll()}
      />
      <WorkflowRunDialog
        open={workflowRunDialogOpen}
        onOpenChange={setWorkflowRunDialogOpen}
        workflow={selectedWorkflow}
        agents={agents}
      />
      <WorkflowHistoryDialog
        open={workflowHistoryDialogOpen}
        onOpenChange={setWorkflowHistoryDialogOpen}
        workflow={selectedWorkflow}
        agents={agents}
      />
      <WorkflowScheduleDialog
        open={workflowScheduleDialogOpen}
        onOpenChange={setWorkflowScheduleDialogOpen}
        workflow={selectedWorkflow}
      />
      <ConfirmDeleteAgent />
      <ConfirmDeleteTeam />
      <ConfirmDeleteWorkflow />
    </div>
  )
}
