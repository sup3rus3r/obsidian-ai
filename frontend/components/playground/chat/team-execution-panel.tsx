"use client"

import { useEffect, useRef, useState } from "react"
import type { AgentStep, AgentToolStep } from "@/types/playground"
import { Brain, Wrench, ChevronDown, ChevronUp, X, AlertCircle, CheckCircle2 } from "lucide-react"

interface TeamExecutionPanelProps {
  isStreaming: boolean
  agentStepLog: AgentStep[]
  agentToolStepLog: AgentToolStep[]
}

type TimelineItem =
  | { kind: "step"; key: string; step: AgentStep }
  | { kind: "tool"; key: string; tool: AgentToolStep }

function stepLabel(step: AgentStep): string {
  switch (step.step) {
    case "routing":
      return "Routing query..."
    case "responding":
      return `${step.agent_name} is responding...`
    case "selected":
      return `Selected ${step.agent_name}${step.router_decision ? ` (${step.router_decision})` : ""}`
    case "completed":
      return `${step.agent_name} completed`
    case "failed":
      return `${step.agent_name} failed${step.error ? `: ${step.error}` : ""}`
    case "synthesizing":
      return "Synthesizing responses..."
    default:
      return step.agent_name
  }
}

function toolLabel(tool: AgentToolStep): string {
  const verb = tool.status === "running" ? "running" : "ran"
  const elapsed = tool.status === "running" && tool.elapsed_seconds ? ` (${tool.elapsed_seconds}s)` : ""
  return `${tool.agent_name}: ${verb} ${tool.tool_name}${elapsed}`
}

export function TeamExecutionPanel({ isStreaming, agentStepLog, agentToolStepLog }: TeamExecutionPanelProps) {
  const [collapsed, setCollapsed] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const [visible, setVisible] = useState(false)
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const hasActivity = agentStepLog.length > 0 || agentToolStepLog.length > 0

  useEffect(() => {
    if (hasActivity) {
      setVisible(true)
      setDismissed(false)
      if (hideTimer.current) {
        clearTimeout(hideTimer.current)
        hideTimer.current = null
      }
    }
  }, [hasActivity])

  useEffect(() => {
    if (!isStreaming && visible) {
      hideTimer.current = setTimeout(() => setVisible(false), 4000)
    }
    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current)
    }
  }, [isStreaming, visible])

  if (!visible || !hasActivity || dismissed) return null

  const items: TimelineItem[] = [
    ...agentStepLog.map((step, i) => ({ kind: "step" as const, key: `s-${step.agent_id}-${step.step}-${i}`, step })),
    ...agentToolStepLog.map((tool, i) => ({ kind: "tool" as const, key: `t-${tool.agent_id}-${tool.tool_name}-${tool.status}-${i}`, tool })),
  ]

  return (
    <div className="fixed bottom-20 right-4 z-40 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-popover shadow-lg">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2 min-w-0">
          <span className={isStreaming ? "h-1.5 w-1.5 rounded-full bg-primary animate-pulse shrink-0" : "h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0"} />
          <span className="text-xs font-medium truncate">Team Execution</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="p-0.5 rounded hover:bg-muted text-muted-foreground"
            aria-label={collapsed ? "Expand" : "Collapse"}
          >
            {collapsed ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
          <button
            onClick={() => setDismissed(true)}
            className="p-0.5 rounded hover:bg-muted text-muted-foreground"
            aria-label="Dismiss"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="max-h-64 overflow-y-auto px-3 py-2 space-y-1.5">
          {items.map((item) => {
            if (item.kind === "step") {
              const isFailed = item.step.step === "failed"
              const isDone = item.step.step === "completed" || item.step.step === "selected"
              return (
                <div key={item.key} className="flex items-start gap-2">
                  <Brain className={isFailed ? "h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" : "h-3.5 w-3.5 text-violet-500 shrink-0 mt-0.5"} />
                  <span className={isFailed ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                    {stepLabel(item.step)}
                  </span>
                  {isDone && <CheckCircle2 className="h-3 w-3 text-emerald-500 shrink-0 mt-0.5 ml-auto" />}
                  {isFailed && <AlertCircle className="h-3 w-3 text-destructive shrink-0 mt-0.5 ml-auto" />}
                </div>
              )
            }
            return (
              <div key={item.key} className="flex items-start gap-2">
                <Wrench className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
                <span className="text-xs text-muted-foreground">{toolLabel(item.tool)}</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
