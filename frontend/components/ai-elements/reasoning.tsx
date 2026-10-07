"use client"

import { cn } from "@/lib/utils"
import { AnimatePresence, motion } from "motion/react"
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
    <div className={cn("rounded-lg border border-border overflow-hidden shadow-sm", className)}>
      <motion.button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        whileHover={{ backgroundColor: "var(--muted)" }}
        whileTap={{ scale: 0.995 }}
        transition={{ duration: 0.15 }}
        className="flex w-full items-center gap-2 bg-muted/40 px-3 py-2 text-left text-sm cursor-pointer"
      >
        <Brain className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-muted-foreground flex-1">
          {isStreaming ? "Thinking..." : "Thought process"}
        </span>
        {isStreaming && (
          <span className="flex items-center gap-0.5">
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="h-1 w-1 rounded-full bg-muted-foreground"
                animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
                transition={{
                  duration: 1,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: i * 0.15,
                }}
              />
            ))}
          </span>
        )}
        <motion.span
          animate={{ rotate: isOpen ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          className="inline-flex"
        >
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        </motion.span>
      </motion.button>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            key="reasoning-content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <div
              ref={contentRef}
              className="border-t border-border bg-background px-3 py-2 text-xs text-muted-foreground italic whitespace-pre-wrap max-h-48 overflow-y-auto"
            >
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export { Reasoning }
