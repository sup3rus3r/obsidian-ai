"use client"

import { useState, useRef, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useSession } from "next-auth/react"
import {
  streamWorkflow,
  type WorkflowStartEvent,
  type StepStartEvent,
  type StepCompleteEvent,
  type WorkflowCompleteEvent,
} from "@/lib/stream"
import type { Workflow, Agent } from "@/types/playground"
import {
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Square,
  GitBranch,
  Circle,
  SkipForward,
  ChevronDown,
  ChevronRight,
} from "lucide-react"
import { MarkdownRenderer } from "@/components/playground/chat/markdown-renderer"
import { cn } from "@/lib/utils"

interface WorkflowRunDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workflow: Workflow | null
  agents: Agent[]
}

function generateRunId(): string {
  const words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima", "mike", "nova", "oscar", "papa", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu"]
  const a = words[Math.floor(Math.random() * words.length)]
  const b = words[Math.floor(Math.random() * words.length)]
  const n = Math.floor(Math.random() * 900) + 100
  return `${a}-${b}-${n}`
}

export function WorkflowRunDialog({
  open,
  onOpenChange,
  workflow,
  agents,
}: WorkflowRunDialogProps) {
  const { data: session } = useSession()

  const [isRunning, setIsRunning] = useState(false)
  const [expandedOutputs, setExpandedOutputs] = useState<Set<number | "final">>(new Set())
  const [activeStepIndex, setActiveStepIndex] = useState<number | undefined>(undefined)
  const [completedSteps, setCompletedSteps] = useState<number[]>([])
  const [stepOutputs, setStepOutputs] = useState<Record<number, string>>({})
  const [streamingStepOrder, setStreamingStepOrder] = useState<number | null>(null)
  const [finalOutput, setFinalOutput] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<"idle" | "running" | "completed" | "failed">("idle")
  const abortRef = useRef<AbortController | null>(null)
  const outputRef = useRef<HTMLDivElement>(null)
  const [currentRunLabel] = useState(generateRunId)

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [finalOutput, stepOutputs, streamingStepOrder])

  const toggleOutput = (key: number | "final") => {
    setExpandedOutputs((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const resetState = () => {
    setIsRunning(false)
    setActiveStepIndex(undefined)
    setCompletedSteps([])
    setStepOutputs({})
    setStreamingStepOrder(null)
    setFinalOutput(null)
    setError(null)
    setStatus("idle")
    setExpandedOutputs(new Set())
  }

  const handleRun = async () => {
    if (!session?.accessToken || !workflow || isRunning) return

    setIsRunning(true)
    setStatus("running")
    setError(null)
    setCompletedSteps([])
    setActiveStepIndex(undefined)
    setStepOutputs({})
    setStreamingStepOrder(null)
    setFinalOutput(null)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamWorkflow(
        session.accessToken,
        workflow.id,
        currentRunLabel,
        (event: WorkflowStartEvent) => { void event },
        (event: StepStartEvent) => {
          const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)
          const idx = sortedSteps.findIndex((s) => s.order === event.step_order)
          setActiveStepIndex(idx >= 0 ? idx : undefined)
          setStreamingStepOrder(event.step_order)
        },
        (_stepOrder: number, _content: string) => { /* no streaming content displayed */ },
        (event: StepCompleteEvent) => {
          const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)
          const idx = sortedSteps.findIndex((s) => s.order === event.step_order)
          if (idx >= 0) setCompletedSteps((prev) => [...prev, idx])
          setStepOutputs((prev) => ({ ...prev, [event.step_order]: event.output }))
          setActiveStepIndex(undefined)
          setStreamingStepOrder(null)
        },
        (stepOrder: number, errorMsg: string) => {
          const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)
          const idx = sortedSteps.findIndex((s) => s.order === stepOrder)
          if (idx >= 0) setActiveStepIndex(idx)
          setError(`Step ${stepOrder} failed: ${errorMsg}`)
          setStatus("failed")
        },
        (event: WorkflowCompleteEvent) => {
          setFinalOutput(event.final_output)
          setStatus("completed")
          setActiveStepIndex(undefined)
          setStreamingStepOrder(null)
          setExpandedOutputs((prev) => new Set([...prev, "final" as const]))
        },
        (_rId: string, errorMsg: string) => {
          setError(errorMsg)
          setStatus("failed")
        },
        controller.signal,
      )
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message)
        setStatus("failed")
      }
    } finally {
      setIsRunning(false)
      abortRef.current = null
    }
  }

  const handleStop = () => {
    abortRef.current?.abort()
    setIsRunning(false)
    setStatus("failed")
    setError("Cancelled by user")
  }

  const handleClose = (v: boolean) => {
    if (!isRunning) {
      resetState()
      onOpenChange(v)
    }
  }

  if (!workflow) return null

  const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)

  const getStepName = (step: typeof sortedSteps[0]) => {
    if (step.node_type && step.node_type !== "agent") {
      return step.node_type.charAt(0).toUpperCase() + step.node_type.slice(1)
    }
    return agents.find((a) => a.id === step.agent_id)?.name || "Agent"
  }

  const nodeTypeColor: Record<string, string> = {
    start: "text-emerald-400",
    end: "text-rose-400",
    condition: "text-amber-400",
    agent: "text-indigo-400",
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="fixed! inset-4! translate-x-0! translate-y-0! top-4! left-4! max-w-none! w-[calc(100%-2rem)]! h-[calc(100vh-2rem)]! flex! flex-col! overflow-hidden p-0!">
        {/* Top bar */}
        <div className="flex items-center justify-between px-6 pr-14 pt-5 pb-4 border-b border-border shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-8 w-8 rounded-lg bg-emerald-500/10 flex items-center justify-center shrink-0">
              <GitBranch className="h-4 w-4 text-emerald-500" />
            </div>
            <div className="min-w-0">
              <DialogHeader>
                <DialogTitle className="font-mono text-base leading-tight">
                  {workflow.name.toUpperCase()}
                </DialogTitle>
              </DialogHeader>
              {workflow.description && (
                <p className="text-xs text-muted-foreground mt-0.5 truncate">{workflow.description}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-[11px] font-mono text-muted-foreground/60 hidden sm:block">
              {currentRunLabel}
            </span>
            {status === "idle" && (
              <Button onClick={handleRun} disabled={isRunning} className="gap-2 h-8 px-4 text-xs font-mono">
                <Play className="h-3.5 w-3.5" />
                RUN
              </Button>
            )}
            {isRunning && (
              <Button variant="destructive" onClick={handleStop} className="gap-2 h-8 px-4 text-xs font-mono">
                <Square className="h-3 w-3" />
                STOP
              </Button>
            )}
            {status === "completed" && (
              <Badge className="text-[10px] bg-green-500/15 text-green-400 border-green-500/30 px-2">
                COMPLETED
              </Badge>
            )}
            {status === "failed" && (
              <Badge className="text-[10px] bg-red-500/15 text-red-400 border-red-500/30 px-2">
                FAILED
              </Badge>
            )}
            {(status === "completed" || status === "failed") && !isRunning && (
              <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => resetState()}>
                Run Again
              </Button>
            )}
          </div>
        </div>

        {/* Main content — two column on wide, stacked on narrow */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {/* Left: pipeline steps */}
          <div className="w-64 shrink-0 border-r border-border flex flex-col overflow-y-auto py-4 px-3 gap-1">
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider px-2 mb-2">
              Pipeline · {sortedSteps.length} steps
            </p>
            {sortedSteps.map((step, i) => {
              const isActive = activeStepIndex === i || streamingStepOrder === step.order
              const isDone = completedSteps.includes(i)
              const output = stepOutputs[step.order]
              const isSkipped = output === "skipped"
              const isFailed = status === "failed" && activeStepIndex === i
              const nt = step.node_type || "agent"
              const color = nodeTypeColor[nt] || nodeTypeColor.agent

              return (
                <div
                  key={step.order}
                  className={cn(
                    "flex items-start gap-2.5 rounded-md px-2 py-2 transition-colors text-left",
                    isActive && "bg-blue-500/8 border border-blue-500/20",
                    isDone && !isActive && "opacity-60",
                    isFailed && "bg-red-500/8 border border-red-500/20",
                  )}
                >
                  <div className="shrink-0 mt-0.5">
                    {isFailed ? (
                      <XCircle className="h-3.5 w-3.5 text-red-400" />
                    ) : isActive ? (
                      <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />
                    ) : isDone && isSkipped ? (
                      <SkipForward className="h-3.5 w-3.5 text-muted-foreground/40" />
                    ) : isDone ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />
                    ) : (
                      <Circle className="h-3.5 w-3.5 text-muted-foreground/30" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={cn("text-[10px] font-semibold uppercase tracking-wide", color)}>
                        {nt}
                      </span>
                    </div>
                    <p className="text-xs font-medium text-foreground leading-snug truncate">
                      {getStepName(step)}
                    </p>
                    {step.task && (
                      <p className="text-[10px] text-muted-foreground leading-snug line-clamp-2 mt-0.5">
                        {step.task}
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Right: output / idle state */}
          <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
            {status === "idle" && (
              <div className="flex-1 flex flex-col items-center justify-center gap-4 p-8 text-center">
                <div className="h-14 w-14 rounded-2xl bg-emerald-500/10 flex items-center justify-center">
                  <GitBranch className="h-7 w-7 text-emerald-500" />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">Ready to run</p>
                  <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                    Click <span className="font-mono font-semibold text-foreground">RUN</span> to execute this workflow. The pipeline will stream progress in real time.
                  </p>
                </div>
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground/60 font-mono border border-border rounded-md px-3 py-1.5 bg-muted/20">
                  Run ID: {currentRunLabel}
                </div>
                <Button onClick={handleRun} disabled={isRunning} className="gap-2 mt-2">
                  <Play className="h-4 w-4" />
                  Run Workflow
                </Button>
              </div>
            )}

            {(status === "running" || status === "completed" || status === "failed") && (
              <div ref={outputRef} className="flex-1 overflow-y-auto p-5 space-y-1.5">
                {/* Step events — accordion */}
                {sortedSteps.map((step) => {
                  const output = stepOutputs[step.order]
                  if (!output) return null
                  const isCondition = step.node_type === "condition"
                  const isSkipped = output === "skipped"
                  const name = getStepName(step)
                  const nt = step.node_type || "agent"
                  const color = nodeTypeColor[nt] || nodeTypeColor.agent
                  // Only agent nodes with real text output can be expanded
                  const hasExpandable = !isSkipped && !isCondition && nt === "agent" && output.trim().length > 0
                  const isExpanded = expandedOutputs.has(step.order)

                  return (
                    <div key={step.order} className={cn(
                      "rounded-md border overflow-hidden text-xs transition-colors",
                      isSkipped ? "border-border/40 bg-muted/10 opacity-50" : "border-border/60 bg-muted/20",
                    )}>
                      <button
                        className={cn(
                          "w-full flex items-center gap-2.5 px-3 py-2 text-left",
                          hasExpandable && "hover:bg-muted/40 cursor-pointer",
                          !hasExpandable && "cursor-default",
                        )}
                        onClick={() => hasExpandable && toggleOutput(step.order)}
                        disabled={!hasExpandable}
                      >
                        {/* status icon */}
                        {isSkipped
                          ? <SkipForward className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0" />
                          : <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0" />
                        }
                        {/* name */}
                        <span className={cn("font-semibold shrink-0", color)}>{name}</span>
                        {/* inline result */}
                        {isSkipped && <span className="text-muted-foreground/50 italic">skipped</span>}
                        {!isSkipped && isCondition && (
                          <span className="text-amber-400 font-mono font-medium">→ {output}</span>
                        )}
                        {!isSkipped && !isCondition && (
                          <span className="text-muted-foreground">done</span>
                        )}
                        {/* chevron for expandable rows */}
                        {hasExpandable && (
                          <span className="ml-auto text-muted-foreground/50">
                            {isExpanded
                              ? <ChevronDown className="h-3.5 w-3.5" />
                              : <ChevronRight className="h-3.5 w-3.5" />
                            }
                          </span>
                        )}
                      </button>
                      {hasExpandable && isExpanded && (
                        <div className="px-4 pb-3 pt-1 border-t border-border/40 text-xs text-foreground max-w-none [&_pre]:my-2 [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_h1]:text-sm [&_h1]:font-bold [&_h2]:text-sm [&_h2]:font-bold [&_h3]:text-xs [&_h3]:font-semibold [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground">
                          <MarkdownRenderer content={output} />
                        </div>
                      )}
                    </div>
                  )
                })}

                {/* Currently running */}
                {streamingStepOrder !== null && (
                  <div className="flex items-center gap-2.5 text-xs bg-blue-500/8 border border-blue-500/20 rounded-md px-3 py-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400 shrink-0" />
                    <span className="text-blue-400 font-medium">
                      {getStepName(sortedSteps.find(s => s.order === streamingStepOrder) || sortedSteps[0])}
                    </span>
                    <span className="text-muted-foreground">running...</span>
                  </div>
                )}

                {/* Final output — accordion */}
                {status === "completed" && finalOutput && (
                  <div className="mt-2 rounded-lg border border-green-500/20 bg-green-500/5 overflow-hidden">
                    <button
                      className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-green-500/8 transition-colors text-left"
                      onClick={() => toggleOutput("final")}
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0" />
                      <span className="text-xs font-semibold text-green-400 flex-1">Final Output</span>
                      {expandedOutputs.has("final")
                        ? <ChevronDown className="h-3.5 w-3.5 text-green-400/60" />
                        : <ChevronRight className="h-3.5 w-3.5 text-green-400/60" />
                      }
                    </button>
                    {expandedOutputs.has("final") && (
                      <div className="px-4 py-3 border-t border-green-500/15 text-xs text-foreground max-w-none [&_pre]:my-2 [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_h1]:text-sm [&_h1]:font-bold [&_h2]:text-sm [&_h2]:font-bold [&_h3]:text-xs [&_h3]:font-semibold [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground">
                        <MarkdownRenderer content={finalOutput} />
                      </div>
                    )}
                  </div>
                )}

                {/* Error */}
                {error && (
                  <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 flex items-start gap-2.5">
                    <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />
                    <span className="text-xs text-red-400">{error}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
