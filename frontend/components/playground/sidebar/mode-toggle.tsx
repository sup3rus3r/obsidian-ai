"use client"

import { usePlaygroundStore } from "@/stores/playground-store"
import { motion } from "motion/react"

export function ModeToggle() {
  const mode = usePlaygroundStore((s) => s.mode)
  const setMode = usePlaygroundStore((s) => s.setMode)

  return (
    <div className="relative flex items-center rounded-lg bg-muted p-2">
      {/* Animated sliding indicator */}
      <motion.div
        className="absolute top-1 bottom-1 left-1 rounded-md bg-background shadow-sm "
        layoutId="mode-toggle-indicator"
        style={{
          width: "calc(50% - 2px)",
          left: mode === "agent" ? 4 : "calc(50% + -3px)",
        }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
      />

      <button
        onClick={() => setMode("agent")}
        className={`relative z-10 flex-1 text-xs font-medium py-1.5 rounded-md transition-colors ${
          mode === "agent"
            ? "text-foreground"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        Agents
      </button>
      <button
        onClick={() => setMode("team")}
        className={`relative z-10 flex-1 text-xs font-medium py-1.5 p rounded-md transition-colors ${
          mode === "team"
            ? "text-foreground"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        Teams
      </button>
    </div>
  )
}
