"use client"

import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { apiClient } from "@/lib/api-client"
import type { Workflow, WorkflowRun, Agent } from "@/types/playground"
import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  ChevronDown,
  ChevronRight,
} from "lucide-react"
import { MarkdownRenderer } from "@/components/playground/chat/markdown-renderer"

interface WorkflowHistoryDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workflow: Workflow | null
  agents: Agent[]
}

function formatDuration(start: string, end?: string): string {
  if (!end) return "—"
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${minutes}m ${remainingSeconds}s`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

const statusConfig = {
  running: { icon: Loader2, color: "text-blue-500", bg: "bg-blue-500/10", label: "Running" },
  completed: { icon: CheckCircle2, color: "text-green-500", bg: "bg-green-500/10", label: "Completed" },
  failed: { icon: XCircle, color: "text-red-500", bg: "bg-red-500/10", label: "Failed" },
  cancelled: { icon: XCircle, color: "text-amber-500", bg: "bg-amber-500/10", label: "Cancelled" },
}

export function WorkflowHistoryDialog({
  open,
  onOpenChange,
  workflow,
  agents,
}: WorkflowHistoryDialogProps) {
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [loading, setLoading] = useState(false)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)

  useEffect(() => {
    if (open && workflow) {
      setLoading(true)
      apiClient
        .listWorkflowRuns(workflow.id)
        .then((data) => setRuns(data))
        .catch(() => setRuns([]))
        .finally(() => setLoading(false))
    } else {
      setRuns([])
      setExpandedRunId(null)
    }
  }, [open, workflow])

  if (!workflow) return null

  const getAgentName = (agentId: string) =>
    agents.find((a) => a.id === agentId)?.name || "Unknown"

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="fixed! inset-4! translate-x-0! translate-y-0! top-4! left-4! max-w-none! w-[calc(100%-2rem)]! h-[calc(100vh-2rem)]! flex! flex-col! overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle className="font-mono">
            {workflow.name.toUpperCase()} — HISTORY
          </DialogTitle>
          <DialogDescription>
            Past executions of this workflow.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 min-h-0 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : runs.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-sm text-muted-foreground">No runs yet. Execute this workflow to see history here.</p>
            </div>
          ) : (
            <div className="space-y-2 pr-4">
              {runs.map((run) => {
                const config = statusConfig[run.status] || statusConfig.failed
                const StatusIcon = config.icon
                const isExpanded = expandedRunId === run.id

                return (
                  <div
                    key={run.id}
                    className="rounded-md border border-border bg-muted/20"
                  >
                    {/* Run header */}
                    <button
                      className="w-full flex items-center gap-3 p-3 text-left hover:bg-muted/40 transition-colors"
                      onClick={() => setExpandedRunId(isExpanded ? null : run.id)}
                    >
                      {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      )}
                      <StatusIcon
                        className={`h-4 w-4 shrink-0 ${config.color} ${run.status === "running" ? "animate-spin" : ""}`}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className={`text-[10px] px-1.5 py-0 ${config.bg} ${config.color}`}>
                            {config.label}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {run.steps.length} step{run.steps.length !== 1 ? "s" : ""}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {formatDuration(run.started_at, run.completed_at)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 mt-0.5">
                          <Clock className="h-3 w-3 text-muted-foreground" />
                          <span className="text-[11px] text-muted-foreground">
                            {formatTime(run.started_at)}
                          </span>
                        </div>
                      </div>
                    </button>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <div className="px-3 pb-3 pt-0 space-y-3 border-t border-border">
                        {/* Input */}
                        {run.input_text && (
                          <div className="pt-2">
                            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                              Input
                            </span>
                            <div className="text-xs text-foreground mt-1 bg-muted/40 rounded p-2 max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_strong]:font-semibold">
                              <MarkdownRenderer content={run.input_text} />
                            </div>
                          </div>
                        )}

                        {/* Steps */}
                        <div>
                          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                            Steps
                          </span>
                          <div className="mt-1 space-y-2">
                            {run.steps.map((step) => {
                              const stepConfig = statusConfig[step.status as keyof typeof statusConfig] || statusConfig.failed
                              const StepIcon = stepConfig.icon
                              return (
                                <div key={step.order} className="rounded border border-border/50 p-2">
                                  <div className="flex items-center gap-1.5">
                                    <StepIcon
                                      className={`h-3 w-3 shrink-0 ${stepConfig.color} ${step.status === "running" ? "animate-spin" : ""}`}
                                    />
                                    <span className="text-[11px] font-mono text-muted-foreground">
                                      {step.order}.
                                    </span>
                                    <span className="text-xs font-medium">{step.agent_name}</span>
                                    <span className="text-[11px] text-muted-foreground ml-auto">
                                      {step.started_at && step.completed_at
                                        ? formatDuration(step.started_at, step.completed_at)
                                        : ""}
                                    </span>
                                  </div>
                                  <p className="text-[11px] text-muted-foreground mt-0.5 pl-5">
                                    {step.task}
                                  </p>
                                  {step.output && (
                                    <div className="text-xs text-foreground mt-1 pl-5 max-w-none [&_pre]:my-2 [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_h1]:text-sm [&_h1]:font-bold [&_h2]:text-sm [&_h2]:font-bold [&_h3]:text-xs [&_h3]:font-semibold [&_h4]:text-xs [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground">
                                      <MarkdownRenderer content={step.output} />
                                    </div>
                                  )}
                                  {step.error && (
                                    <p className="text-xs text-red-500 mt-1 pl-5">
                                      {step.error}
                                    </p>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </div>

                        {/* Error */}
                        {run.error && (
                          <div>
                            <span className="text-[10px] font-medium text-red-500 uppercase tracking-wider">
                              Error
                            </span>
                            <p className="text-xs text-red-500 mt-1">{run.error}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
