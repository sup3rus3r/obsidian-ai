"use client"

import { useState, useCallback } from "react"
import { FileCode, Copy, Check, ExternalLink } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import { cn } from "@/lib/utils"

interface ArtifactProps {
  title: string
  language?: string
  children: string
  className?: string
}

export function Artifact({ title, language, children, className }: ArtifactProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(children)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [children])

  return (
    <div
      className={cn(
        "rounded-lg border border-border overflow-hidden my-3",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-muted/40 border-b border-border">
        <div className="flex items-center gap-2 min-w-0">
          <FileCode className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-medium truncate">{title}</span>
          {language && (
            <span className="text-[10px] text-muted-foreground font-mono px-1.5 py-0.5 rounded bg-muted">
              {language}
            </span>
          )}
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors shrink-0"
        >
          <AnimatePresence mode="wait">
            {copied ? (
              <motion.span
                key="copied"
                className="flex items-center gap-1"
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.15 }}
              >
                <Check className="h-3 w-3 text-emerald-500" />
              </motion.span>
            ) : (
              <motion.span
                key="copy"
                className="flex items-center gap-1"
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.15 }}
              >
                <Copy className="h-3 w-3" />
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </div>

      {/* Content */}
      <div className="p-3 bg-background">
        <pre className="overflow-x-auto text-[13px] font-mono text-foreground whitespace-pre-wrap">
          {children}
        </pre>
      </div>
    </div>
  )
}
