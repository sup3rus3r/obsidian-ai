"use client"

import { useState } from "react"
import { CheckCircle2, ChevronsUpDown, Loader2, ListTodo } from "lucide-react"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import type { PlanData } from "@/types/playground"

interface PlanProps {
  plan: PlanData
  isStreaming?: boolean
  className?: string
}

function ShimmerText({ children, active }: { children: string; active: boolean }) {
  if (!active) return <>{children}</>
  return (
    <span className="relative inline-block overflow-hidden rounded">
      <span className="relative z-10">{children}</span>
      <span
        className="absolute inset-0 -translate-x-full animate-[shimmer_1.5s_infinite] bg-gradient-to-r from-transparent via-foreground/10 to-transparent"
        aria-hidden
      />
    </span>
  )
}

export function Plan({ plan, isStreaming = false, className }: PlanProps) {
  const [open, setOpen] = useState(true)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className={cn("shadow-none gap-0 py-0 overflow-hidden", className)}>
        <CardHeader className="py-3 px-4">
          <div className="flex items-start gap-2">
            <ListTodo className="h-4 w-4 text-primary mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <CardTitle className="text-sm">
                <ShimmerText active={isStreaming && !plan.title}>
                  {plan.title || "Generating plan..."}
                </ShimmerText>
              </CardTitle>
              {plan.description && (
                <CardDescription className="text-xs mt-0.5">
                  <ShimmerText active={isStreaming}>
                    {plan.description}
                  </ShimmerText>
                </CardDescription>
              )}
            </div>
          </div>
          <CardAction>
            <CollapsibleTrigger asChild>
              <button
                className="flex items-center justify-center h-7 w-7 rounded text-muted-foreground hover:bg-muted transition-colors"
                aria-label="Toggle plan"
              >
                <ChevronsUpDown className="h-3.5 w-3.5" />
              </button>
            </CollapsibleTrigger>
          </CardAction>
        </CardHeader>

        <CollapsibleContent>
          <CardContent className="pb-3 px-4 pt-0">
            {plan.steps.length > 0 ? (
              <ol className="space-y-1.5">
                {plan.steps.map((step, i) => {
                  const isLastStep = i === plan.steps.length - 1
                  const isActiveStep = isStreaming && isLastStep && !plan.isComplete
                  return (
                    <li key={i} className="flex items-start gap-2">
                      {isActiveStep ? (
                        <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin shrink-0 mt-0.5" />
                      ) : (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0 mt-0.5" />
                      )}
                      <span className="text-xs text-foreground leading-snug">{step}</span>
                    </li>
                  )
                })}
              </ol>
            ) : isStreaming ? (
              <div className="flex items-center gap-2 py-1">
                <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />
                <span className="text-xs text-muted-foreground">Building plan...</span>
              </div>
            ) : null}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
