"use client"

import { cn } from "@/lib/utils"
import { ChevronDown, Brain } from "lucide-react"
import { useEffect, useRef, useState } from "react"

export type ReasoningProps = {
  children: string
  isStreaming?: boolean
  className?: string
}

const Reasoning = ({ children, isStreaming, className }: ReasoningProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [wasAutoOpened, setWasAutoOpened] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)

  // Auto-open while streaming, auto-close when done
  useEffect(() => {
    if (isStreaming && !wasAutoOpened) {
      setIsOpen(true)
      setWasAutoOpened(true)
    }
    if (!isStreaming && wasAutoOpened) {
      setIsOpen(false)
      setWasAutoOpened(false)
    }
  }, [isStreaming, wasAutoOpened])

  // Auto-scroll content during streaming
  useEffect(() => {
    if (isOpen && isStreaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [children, isOpen, isStreaming])

  return (
    <div className={cn("rounded-lg border border-border overflow-hidden", className)}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center gap-2 bg-muted/40 px-3 py-2 text-left text-sm cursor-pointer hover:bg-muted/60 transition-colors"
      >
        <Brain className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground flex-1">
          {isStreaming ? "Thinking..." : "Thought process"}
        </span>
        {isStreaming && (
          <span className="flex gap-0.5">
            <span className="h-1 w-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:0ms]" />
            <span className="h-1 w-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:150ms]" />
            <span className="h-1 w-1 rounded-full bg-muted-foreground animate-bounce [animation-delay:300ms]" />
          </span>
        )}
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-muted-foreground transition-transform duration-200",
            isOpen && "rotate-180"
          )}
        />
      </button>

      <div
        className={cn(
          "grid transition-all duration-200 ease-out",
          isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}
      >
        <div className="overflow-hidden">
          <div
            ref={contentRef}
            className="border-t border-border bg-background px-3 py-2 text-xs text-muted-foreground italic whitespace-pre-wrap max-h-48 overflow-y-auto"
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}

export { Reasoning }
