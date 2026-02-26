"use client"

import { cn } from "@/lib/utils"
import { Search } from "lucide-react"

interface ResearchProgressProps {
  round: number
  maxRounds: number
  className?: string
}

export function ResearchProgress({ round, maxRounds, className }: ResearchProgressProps) {
  const progress = Math.min((round / maxRounds) * 100, 100)

  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-md bg-blue-500/8 border border-blue-500/20 px-3 py-2",
        className
      )}
    >
      <Search className="h-3.5 w-3.5 text-blue-500 shrink-0 animate-pulse" />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-blue-600 dark:text-blue-400">
          Researching... step {round} of {maxRounds}
        </div>
        <div className="mt-1 h-1 w-full rounded-full bg-blue-500/15 overflow-hidden">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
    </div>
  )
}
