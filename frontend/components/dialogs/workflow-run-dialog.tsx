"use client"

import { useState, useRef, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { WorkflowStepsView } from "@/components/playground/workflow-steps-view"
import { useSession } from "next-auth/react"
import {
  streamWorkflow,
  type WorkflowStartEvent,
  type StepStartEvent,
  type StepCompleteEvent,
  type WorkflowCompleteEvent,
} from "@/lib/stream"
import type { Workflow, Agent, WorkflowStepResult } from "@/types/playground"
import {
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Square,
} from "lucide-react"
import { MarkdownRenderer } from "@/components/playground/chat/markdown-renderer"

interface WorkflowRunDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workflow: Workflow | null
  agents: Agent[]
}

export function WorkflowRunDialog({
  open,
  onOpenChange,
  workflow,
  agents,
}: WorkflowRunDialogProps) {
  const { data: session } = useSession()

  const [input, setInput] = useState("")
  const [isRunning, setIsRunning] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [activeStepIndex, setActiveStepIndex] = useState<number | undefined>(undefined)
  const [completedSteps, setCompletedSteps] = useState<number[]>([])
  const [failedStep, setFailedStep] = useState<number | undefined>(undefined)
  const [stepOutputs, setStepOutputs] = useState<Record<number, string>>({})
  const [streamingContent, setStreamingContent] = useState("")
  const [streamingStepOrder, setStreamingStepOrder] = useState<number | null>(null)
  const [finalOutput, setFinalOutput] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<"idle" | "running" | "completed" | "failed">("idle")
  const abortRef = useRef<AbortController | null>(null)
  const outputRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [streamingContent, finalOutput, stepOutputs])

  const resetState = () => {
    setInput("")
    setIsRunning(false)
    setRunId(null)
    setActiveStepIndex(undefined)
    setCompletedSteps([])
    setFailedStep(undefined)
    setStepOutputs({})
    setStreamingContent("")
    setStreamingStepOrder(null)
    setFinalOutput(null)
    setError(null)
    setStatus("idle")
  }

  const handleRun = async () => {
    if (!session?.accessToken || !workflow || !input.trim() || isRunning) return

    setIsRunning(true)
    setStatus("running")
    setError(null)
    setCompletedSteps([])
    setActiveStepIndex(undefined)
    setFailedStep(undefined)
    setStepOutputs({})
    setStreamingContent("")
    setStreamingStepOrder(null)
    setFinalOutput(null)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamWorkflow(
        session.accessToken,
        workflow.id,
        input.trim(),
        // onWorkflowStart
        (event: WorkflowStartEvent) => {
          setRunId(event.run_id)
        },
        // onStepStart
        (event: StepStartEvent) => {
          const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)
          const idx = sortedSteps.findIndex((s) => s.order === event.step_order)
          setActiveStepIndex(idx >= 0 ? idx : undefined)
          setStreamingContent("")
          setStreamingStepOrder(event.step_order)
        },
        // onStepContentDelta
        (stepOrder: number, content: string) => {
          setStreamingContent((prev) => prev + content)
        },
        // onStepComplete
        (event: StepCompleteEvent) => {
          const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)
          const idx = sortedSteps.findIndex((s) => s.order === event.step_order)
          if (idx >= 0) {
            setCompletedSteps((prev) => [...prev, idx])
          }
          setStepOutputs((prev) => ({ ...prev, [event.step_order]: event.output }))
          setActiveStepIndex(undefined)
          setStreamingContent("")
          setStreamingStepOrder(null)
        },
        // onStepError
        (stepOrder: number, errorMsg: string) => {
          const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)
          const idx = sortedSteps.findIndex((s) => s.order === stepOrder)
          if (idx >= 0) {
            setFailedStep(idx)
          }
          setError(`Step ${stepOrder} failed: ${errorMsg}`)
          setStatus("failed")
        },
        // onWorkflowComplete
        (event: WorkflowCompleteEvent) => {
          setFinalOutput(event.final_output)
          setStatus("completed")
          setActiveStepIndex(undefined)
          setStreamingContent("")
        },
        // onWorkflowError
        (rId: string, errorMsg: string) => {
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

  const handleClose = (open: boolean) => {
    if (!isRunning) {
      resetState()
      onOpenChange(open)
    }
  }

  if (!workflow) return null

  const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="fixed! inset-4! translate-x-0! translate-y-0! top-4! left-4! max-w-none! w-[calc(100%-2rem)]! h-[calc(100vh-2rem)]! flex! flex-col! overflow-hidden">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2 font-mono">
            {workflow.name.toUpperCase()}
            {status === "completed" && (
              <Badge variant="secondary" className="text-[10px] bg-green-500/10 text-green-500">
                COMPLETED
              </Badge>
            )}
            {status === "failed" && (
              <Badge variant="secondary" className="text-[10px] bg-red-500/10 text-red-500">
                FAILED
              </Badge>
            )}
            {status === "running" && (
              <Badge variant="secondary" className="text-[10px] bg-blue-500/10 text-blue-500">
                RUNNING
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {workflow.description || "Execute this workflow by providing an input."}
          </DialogDescription>
        </DialogHeader>

        {/* Pipeline view — always visible, not scrollable */}
        <div className="shrink-0">
          <WorkflowStepsView
            steps={workflow.steps}
            agents={agents}
            activeStepIndex={activeStepIndex}
            completedSteps={completedSteps}
            defaultOpen={true}
            title={`Pipeline — ${sortedSteps.length} step${sortedSteps.length !== 1 ? "s" : ""}`}
          />
        </div>

        {/* Input */}
        {status === "idle" && (
          <div className="flex gap-2 shrink-0">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Enter a run label..."
              className="flex-1 text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  handleRun()
                }
              }}
            />
            <Button
              onClick={handleRun}
              disabled={!input.trim() || isRunning}
              size="sm"
              className="gap-1.5"
            >
              <Play className="h-3.5 w-3.5" />
              Run
            </Button>
          </div>
        )}

        {/* Running — stop button */}
        {isRunning && (
          <div className="flex justify-end shrink-0">
            <Button variant="destructive" size="sm" onClick={handleStop} className="gap-1.5">
              <Square className="h-3 w-3" />
              Stop
            </Button>
          </div>
        )}

        {/* Output area — scrollable */}
        {(status === "running" || status === "completed" || status === "failed") && (
          <div
            ref={outputRef}
            className="flex-1 min-h-0 overflow-y-auto rounded-md border border-border bg-muted/30 p-3"
          >
            <div className="space-y-3 text-sm">
              {/* Completed step outputs */}
              {sortedSteps.map((step) => {
                const output = stepOutputs[step.order]
                if (!output) return null
                const agentName = agents.find((a) => a.id === step.agent_id)?.name || "Agent"
                return (
                  <div key={step.order} className="space-y-1">
                    <div className="flex items-center gap-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                      <span className="text-xs font-medium text-muted-foreground">
                        Step {step.order} — {agentName}
                      </span>
                    </div>
                    <div className="text-xs text-foreground pl-5 max-w-none [&_pre]:my-2 [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_h1]:text-sm [&_h1]:font-bold [&_h2]:text-sm [&_h2]:font-bold [&_h3]:text-xs [&_h3]:font-semibold [&_h4]:text-xs [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground">
                      <MarkdownRenderer content={output} />
                    </div>
                  </div>
                )
              })}

              {/* Streaming content for current step */}
              {streamingContent && streamingStepOrder !== null && (
                <div className="space-y-1">
                  <div className="flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500 shrink-0" />
                    <span className="text-xs font-medium text-muted-foreground">
                      Step {streamingStepOrder} — streaming...
                    </span>
                  </div>
                  <div className="text-xs text-foreground pl-5 max-w-none [&_pre]:my-2 [&_p]:my-1 [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-4 [&_h1]:text-sm [&_h1]:font-bold [&_h2]:text-sm [&_h2]:font-bold [&_h3]:text-xs [&_h3]:font-semibold [&_h4]:text-xs [&_strong]:font-semibold [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground">
                    <MarkdownRenderer content={streamingContent} />
                  </div>
                </div>
              )}

              {/* Final output */}
              {status === "completed" && finalOutput && (
                <div className="pt-2 border-t border-border space-y-1">
                  <div className="flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                    <span className="text-xs font-semibold text-green-600">Workflow Complete</span>
                  </div>
                </div>
              )}

              {/* Error */}
              {error && (
                <div className="pt-2 border-t border-border space-y-1">
                  <div className="flex items-center gap-1.5">
                    <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                    <span className="text-xs font-medium text-red-500">{error}</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Run again */}
        {(status === "completed" || status === "failed") && !isRunning && (
          <div className="flex justify-end gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                resetState()
              }}
            >
              Run Again
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleClose(false)}
            >
              Close
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
