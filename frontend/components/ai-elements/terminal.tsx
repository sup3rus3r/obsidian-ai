"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AnimatePresence, motion } from "motion/react"
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
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 300, damping: 28 }}
      className={cn(
        "flex flex-col overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 text-zinc-100 shadow-sm",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900/60 px-3 py-2">
        <TerminalIcon className="h-3.5 w-3.5 text-zinc-400 shrink-0" />
        <span className="flex-1 font-mono text-xs text-zinc-400">Terminal</span>

        {isStreaming && (
          <motion.span
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            className="text-[10px] text-emerald-400 font-medium"
          >
            running
          </motion.span>
        )}

        <motion.button
          onClick={handleCopy}
          whileHover={{ backgroundColor: "rgb(39 39 42)" }}
          whileTap={{ scale: 0.92 }}
          transition={{ duration: 0.15 }}
          className="flex items-center justify-center h-6 w-6 rounded text-zinc-500 hover:text-zinc-200"
          title="Copy output"
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={copied ? "check" : "copy"}
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.6 }}
              transition={{ duration: 0.15 }}
              className="inline-flex"
            >
              {copied
                ? <Check className="h-3 w-3 text-emerald-400" />
                : <Copy className="h-3 w-3" />
              }
            </motion.span>
          </AnimatePresence>
        </motion.button>

        {onClear && (
          <motion.button
            onClick={onClear}
            whileHover={{ backgroundColor: "rgb(39 39 42)" }}
            whileTap={{ scale: 0.92 }}
            transition={{ duration: 0.15 }}
            className="flex items-center justify-center h-6 w-6 rounded text-zinc-500 hover:text-zinc-200"
            title="Clear"
          >
            <Trash2 className="h-3 w-3" />
          </motion.button>
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
    </motion.div>
  )
}
