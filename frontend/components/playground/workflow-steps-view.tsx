"use client"

import {
  Steps,
  StepsTrigger,
  StepsContent,
  StepsItem,
  StepsBar,
} from "@/components/ai-elements/steps"
import { Bot, CheckCircle2, Circle, Loader2 } from "lucide-react"
import type { WorkflowStep, Agent } from "@/types/playground"

interface WorkflowStepsViewProps {
  steps: WorkflowStep[]
  agents: Agent[]
  activeStepIndex?: number
  completedSteps?: number[]
  defaultOpen?: boolean
  title?: string
}

export function WorkflowStepsView({
  steps,
  agents,
  activeStepIndex,
  completedSteps = [],
  defaultOpen = true,
  title,
}: WorkflowStepsViewProps) {
  const sortedSteps = [...steps].sort((a, b) => a.order - b.order)

  const getStepIcon = (index: number) => {
    if (completedSteps.includes(index)) {
      return <CheckCircle2 className="size-4 text-green-500" />
    }
    if (activeStepIndex === index) {
      return <Loader2 className="size-4 animate-spin text-blue-500" />
    }
    return <Circle className="size-4 text-muted-foreground" />
  }

  const getAgentName = (agentId: string) => {
    return agents.find((a) => a.id === agentId)?.name || "Unknown Agent"
  }

  return (
    <Steps defaultOpen={defaultOpen}>
      <StepsTrigger
        leftIcon={<Bot className="size-4 text-emerald-500" />}
      >
        {title || `${sortedSteps.length} step${sortedSteps.length !== 1 ? "s" : ""}`}
      </StepsTrigger>
      <StepsContent
        bar={
          <StepsBar className="bg-emerald-500/20" />
        }
      >
        {sortedSteps.map((step, index) => (
          <StepsItem key={`${step.agent_id}-${step.order}`}>
            <div className="flex items-start gap-2 py-1">
              <span className="mt-0.5 shrink-0">
                {getStepIcon(index)}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">
                    {step.order}.
                  </span>
                  <span className="text-xs font-medium text-foreground truncate">
                    {getAgentName(step.agent_id)}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                  {step.task}
                </p>
              </div>
            </div>
          </StepsItem>
        ))}
      </StepsContent>
    </Steps>
  )
}
