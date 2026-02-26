"use client"

import { ExternalLink, Globe } from "lucide-react"
import { cn } from "@/lib/utils"

export interface Source {
  url: string
  title?: string
}

interface SourcesProps {
  sources: Source[]
  className?: string
}

function extractDomain(url: string): string {
  try {
    return new URL(url).hostname.replace("www.", "")
  } catch {
    return url
  }
}

export function Sources({ sources, className }: SourcesProps) {
  if (sources.length === 0) return null

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
        <Globe className="h-3 w-3" />
        Sources
      </div>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((source, i) => (
          <a
            key={i}
            href={source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-muted/50 border border-border text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted transition-colors group"
          >
            <span className="truncate max-w-[200px]">
              {source.title || extractDomain(source.url)}
            </span>
            <ExternalLink className="h-2.5 w-2.5 shrink-0 opacity-50 group-hover:opacity-100 transition-opacity" />
          </a>
        ))}
      </div>
    </div>
  )
}

/**
 * SourceList — accepts SSE-driven { url, title? } objects (from source_url events).
 * Renders identically to Sources but without requiring the full Source[] type.
 */
export function SourceList({
  sources,
  className,
}: {
  sources: { url: string; title?: string }[]
  className?: string
}) {
  if (sources.length === 0) return null
  return (
    <Sources
      sources={sources.map((s) => ({ url: s.url, title: s.title }))}
      className={className}
    />
  )
}

/**
 * Extract URLs from tool call results to display as sources.
 */
export function extractSourcesFromToolCalls(
  toolCalls: Array<{ name: string; result?: string }>
): Source[] {
  const urls = new Set<string>()
  const sources: Source[] = []

  for (const tc of toolCalls) {
    if (!tc.result) continue
    // Match URLs in tool results
    const urlRegex = /https?:\/\/[^\s<>"{}|\\^`\[\]]+/g
    const matches = tc.result.match(urlRegex)
    if (matches) {
      for (const url of matches) {
        // Clean trailing punctuation
        const cleaned = url.replace(/[.,;:!?)]+$/, "")
        if (!urls.has(cleaned)) {
          urls.add(cleaned)
          sources.push({ url: cleaned })
        }
      }
    }
  }

  return sources.slice(0, 6) // Cap at 6 sources
}
