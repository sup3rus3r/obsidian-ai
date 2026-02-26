"use client"

import { useState } from "react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"
import { Globe, ChevronDown, ExternalLink, Maximize2, Minimize2 } from "lucide-react"

interface WebPreviewProps {
  content: string
  title?: string
  className?: string
}

function isUrl(str: string): boolean {
  return /^https?:\/\//i.test(str.trim())
}

function isHtml(str: string): boolean {
  const trimmed = str.trim().toLowerCase()
  return trimmed.startsWith("<!doctype") || trimmed.startsWith("<html")
}

export function WebPreview({ content, title, className }: WebPreviewProps) {
  const [expanded, setExpanded] = useState(false)
  const url = isUrl(content) ? content.trim() : null
  const html = !url && isHtml(content) ? content : null

  if (!url && !html) return null

  const displayTitle = title || (url ? new URL(url).hostname : "Preview")

  return (
    <Collapsible defaultOpen className={cn("rounded-lg border border-border overflow-hidden", className)}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 bg-muted/40 px-3 py-2 text-left text-sm transition-colors hover:bg-muted/60 cursor-pointer group">
        <Globe className="h-3.5 w-3.5 text-blue-500 shrink-0" />
        <span className="text-xs font-medium flex-1 truncate">{displayTitle}</span>
        {url && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
        <button
          onClick={(e) => {
            e.stopPropagation()
            setExpanded(!expanded)
          }}
          className="text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? (
            <Minimize2 className="h-3 w-3" />
          ) : (
            <Maximize2 className="h-3 w-3" />
          )}
        </button>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>

      <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
        <div className="border-t border-border bg-background">
          {url ? (
            <iframe
              src={url}
              sandbox="allow-scripts allow-same-origin"
              className={cn(
                "w-full border-0 transition-all duration-300",
                expanded ? "h-[600px]" : "h-[300px]"
              )}
              title={displayTitle}
            />
          ) : html ? (
            <iframe
              srcDoc={html}
              sandbox="allow-scripts"
              className={cn(
                "w-full border-0 transition-all duration-300",
                expanded ? "h-[600px]" : "h-[300px]"
              )}
              title={displayTitle}
            />
          ) : null}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
