"use client"

import { ArrowDown } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import { cn } from "@/lib/utils"

interface ScrollButtonProps {
  visible: boolean
  onClick: () => void
  className?: string
}

export function ScrollButton({ visible, onClick, className }: ScrollButtonProps) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.button
          initial={{ opacity: 0, scale: 0.8, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.8, y: 10 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          onClick={onClick}
          className={cn(
            "z-10",
            "flex items-center gap-1.5 px-3 py-1.5 rounded-full",
            "bg-background/90 backdrop-blur-sm border shadow-lg",
            "text-xs text-muted-foreground hover:text-foreground",
            "cursor-pointer transition-colors",
            className
          )}
        >
          <ArrowDown className="h-3 w-3" />
          Scroll to bottom
        </motion.button>
      )}
    </AnimatePresence>
  )
}
