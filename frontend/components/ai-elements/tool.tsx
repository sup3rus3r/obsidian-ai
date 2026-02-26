"use client"

import { useState } from "react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import {
  CheckCircle,
  ChevronDown,
  Loader2,
  XCircle,
  Wrench,
  Server,
  Eye,
  EyeOff,
} from "lucide-react"
import { WebPreview } from "./web-preview"
import { WeatherCard } from "./generative-ui/weather-card"
import { SearchResultsCard } from "./generative-ui/search-results-card"
import { CalculatorCard } from "./generative-ui/calculator-card"
import { DateTimeCard } from "./generative-ui/datetime-card"
import { StatCard } from "./generative-ui/stat-card"

export type ToolState =
  | "pending"
  | "running"
  | "completed"
  | "error"

export type ToolProps = {
  name: string
  state: ToolState
  input?: Record<string, unknown> | string
  output?: string
  className?: string
  defaultOpen?: boolean
}

function parseInput(input: Record<string, unknown> | string | undefined): Record<string, unknown> | null {
  if (!input) return null
  if (typeof input === "string") {
    try {
      return JSON.parse(input)
    } catch {
      return null
    }
  }
  return input
}

export function cleanToolName(name: string): { displayName: string; serverName?: string } {
  if (name.startsWith("mcp__")) {
    const parts = name.split("__")
    if (parts.length === 3) {
      return { displayName: parts[2], serverName: parts[1] }
    }
  }
  return { displayName: name }
}

function extractPreviewContent(output: string): string | null {
  const trimmed = output.trim()
  const lower = trimmed.toLowerCase()

  // Direct URL
  if (/^https?:\/\//i.test(trimmed)) return trimmed

  // Direct HTML document (no fencing)
  if (lower.startsWith("<!doctype") || lower.startsWith("<html")) return trimmed

  // Fenced code block: ```html, ```jsx, ```tsx — extract inner content
  const codeBlockMatch = trimmed.match(/```(?:html|jsx|tsx)?\s*\n([\s\S]*?)```/)
  if (codeBlockMatch) {
    return codeBlockMatch[1].trim()
  }

  // HTML document embedded anywhere in text (e.g. after an explanation paragraph)
  const embeddedDoc = trimmed.match(/<!doctype[\s\S]*?<\/html>/i) || trimmed.match(/<html[\s\S]*?<\/html>/i)
  if (embeddedDoc) return embeddedDoc[0].trim()

  // Any HTML fragment that starts with a tag (e.g. tool returns "<div>...</div>")
  if (/^<[a-zA-Z]/.test(trimmed) && /<\/[a-zA-Z]>/.test(trimmed)) return trimmed

  return null
}

function isPreviewable(output: string): boolean {
  return extractPreviewContent(output) !== null
}

export function renderGenerativeUI(name: string, output: string): React.ReactNode | null {
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(output)
  } catch {
    return null
  }
  if (typeof parsed !== "object" || parsed === null) return null

  switch (name) {
    case "get_weather":
      return <WeatherCard data={parsed as Parameters<typeof WeatherCard>[0]["data"]} />
    case "web_search":
      return <SearchResultsCard data={parsed as Parameters<typeof SearchResultsCard>[0]["data"]} />
    case "calculator":
      return <CalculatorCard data={parsed as Parameters<typeof CalculatorCard>[0]["data"]} />
    case "get_datetime":
      return <DateTimeCard data={parsed as Parameters<typeof DateTimeCard>[0]["data"]} />
    case "render_ui":
      if (parsed._ui_type === "stat") {
        return <StatCard data={parsed as Parameters<typeof StatCard>[0]["data"]} />
      }
      return null
    default:
      if (parsed._ui_type === "stat") {
        return <StatCard data={parsed as Parameters<typeof StatCard>[0]["data"]} />
      }
      return null
  }
}

const Tool = ({ name, state, input, output, className, defaultOpen = false }: ToolProps) => {
  const parsed = parseInput(input)
  const { displayName, serverName } = cleanToolName(name)
  // Generative UI is rendered externally by MessageBubble; suppress it inside the tool block
  const hasGenerativeUI = state === "completed" && output ? renderGenerativeUI(displayName, output) !== null : false
  const hasDetails = (parsed && Object.keys(parsed).length > 0) || (!hasGenerativeUI && output)
  const canPreview = !hasGenerativeUI && output && isPreviewable(output)
  const [showPreview, setShowPreview] = useState(canPreview)

  const getStateIcon = () => {
    switch (state) {
      case "running":
      case "pending":
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
      case "completed":
        return <CheckCircle className="h-4 w-4 text-emerald-500" />
      case "error":
        return <XCircle className="h-4 w-4 text-red-500" />
    }
  }

  const getStateBadge = () => {
    const base = "px-1.5 py-0.5 rounded-full text-[10px] font-medium"
    switch (state) {
      case "pending":
      case "running":
        return (
          <span className={cn(base, "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400")}>
            {state === "pending" ? "Pending" : "Running"}
          </span>
        )
      case "completed":
        return (
          <span className={cn(base, "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400")}>
            Completed
          </span>
        )
      case "error":
        return (
          <span className={cn(base, "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400")}>
            Error
          </span>
        )
    }
  }

  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className={cn("overflow-hidden rounded-lg border border-border", className)}
    >
      <CollapsibleTrigger
        className={cn(
          "flex w-full items-center gap-2 bg-muted/40 px-3 py-2 text-left text-sm transition-colors",
          hasDetails ? "cursor-pointer hover:bg-muted/60" : "cursor-default"
        )}
        disabled={!hasDetails}
      >
        {getStateIcon()}
        <Wrench className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-mono text-xs font-medium flex-1">{displayName}</span>
        {serverName && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
            <Server className="h-2.5 w-2.5" />
            {serverName}
          </span>
        )}
        {getStateBadge()}
        {hasDetails && (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
        )}
      </CollapsibleTrigger>

      {hasDetails && (
        <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
          <div className="border-t border-border bg-background p-3 space-y-2">
            {parsed && Object.keys(parsed).length > 0 && (
              <div>
                <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">Input</div>
                <div className="rounded bg-muted/30 border border-border px-2 py-1.5 font-mono text-xs space-y-0.5">
                  {Object.entries(parsed).map(([key, value]) => (
                    <div key={key}>
                      <span className="text-muted-foreground">{key}:</span>{" "}
                      <span>{typeof value === "string" ? value : JSON.stringify(value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {output && !hasGenerativeUI && (
              <div>
                <div className="flex items-center justify-between mb-1">
                  <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Output</div>
                  {canPreview && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setShowPreview(!showPreview)
                      }}
                      className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {showPreview ? (
                        <>
                          <EyeOff className="h-3 w-3" /> Raw
                        </>
                      ) : (
                        <>
                          <Eye className="h-3 w-3" /> Preview
                        </>
                      )}
                    </button>
                  )}
                </div>
                {showPreview && canPreview ? (
                  <WebPreview content={extractPreviewContent(output)!} />
                ) : (
                  <div className="rounded bg-muted/30 border border-border px-2 py-1.5 font-mono text-xs max-h-40 overflow-auto whitespace-pre-wrap">
                    {output}
                  </div>
                )}
              </div>
            )}
          </div>
        </CollapsibleContent>
      )}
    </Collapsible>
  )
}

export { Tool }
