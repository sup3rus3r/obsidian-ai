"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Check, Copy, Terminal as TerminalIcon, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface TerminalProps {
  output: string
  isStreaming?: boolean
  onClear?: () => void
  className?: string
}

export function Terminal({ output, isStreaming = false, onClear, className }: TerminalProps) {
  const [copied, setCopied] = useState(false)
  const contentRef = useRef<HTMLPreElement>(null)

  // Auto-scroll to bottom as output grows
  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [output])

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(output)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard not available
    }
  }, [output])

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900/60 px-3 py-2">
        <TerminalIcon className="h-3.5 w-3.5 text-zinc-400 shrink-0" />
        <span className="flex-1 font-mono text-xs text-zinc-400">Terminal</span>

        {isStreaming && (
          <span className="text-[10px] text-emerald-400 font-medium animate-pulse">running</span>
        )}

        <button
          onClick={handleCopy}
          className="flex items-center justify-center h-6 w-6 rounded text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
          title="Copy output"
        >
          {copied
            ? <Check className="h-3 w-3 text-emerald-400" />
            : <Copy className="h-3 w-3" />
          }
        </button>

        {onClear && (
          <button
            onClick={onClear}
            className="flex items-center justify-center h-6 w-6 rounded text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 transition-colors"
            title="Clear"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* Content */}
      <pre
        ref={contentRef}
        className="max-h-80 overflow-auto p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-zinc-100"
      >
        {output || <span className="text-zinc-600">No output yet...</span>}
        {isStreaming && (
          <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-zinc-100 align-middle" />
        )}
      </pre>
    </div>
  )
}
