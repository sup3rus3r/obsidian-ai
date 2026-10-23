"use client"

import { useState } from "react"
import { Users, Check, X, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AppRoutes } from "@/app/api/routes"
import type { ThreadContinueEvent } from "@/types/playground"

interface ThreadContinueApprovalProps {
  event: ThreadContinueEvent
  accessToken: string
  onResolved: (status: "continue" | "stop") => void
}

export function ThreadContinueApproval({ event, accessToken, onResolved }: ThreadContinueApprovalProps) {
  const [loading, setLoading] = useState(false)
  const [resolved, setResolved] = useState<"continue" | "stop" | null>(null)

  const handleDecision = async (decision: "continue" | "stop") => {
    setLoading(true)
    try {
      const url =
        decision === "continue"
          ? AppRoutes.ThreadContinue(event.session_id, event.approval_id)
          : AppRoutes.ThreadStop(event.session_id, event.approval_id)
      await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      setResolved(decision)
      onResolved(decision)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-cyan-500 shrink-0" />
        <span className="text-xs font-medium text-cyan-600 dark:text-cyan-400">
          Teammates are still discussing
        </span>
      </div>

      <p className="text-xs text-muted-foreground">
        This teammate discussion has gone {event.hop_count} rounds (limit {event.soft_cap}). Continue letting
        them work it out, or stop here and have the agent answer with what it has?
      </p>

      {resolved ? (
        <div
          className={`flex items-center gap-1.5 text-xs font-medium ${
            resolved === "continue" ? "text-emerald-500" : "text-muted-foreground"
          }`}
        >
          {resolved === "continue" ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
          {resolved === "continue" ? "Continuing" : "Stopped"}
        </div>
      ) : (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs border-emerald-500/50 text-emerald-600 hover:bg-emerald-500/10 hover:border-emerald-500"
            disabled={loading}
            onClick={() => handleDecision("continue")}
          >
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            <span className="ml-1">Let them continue</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs"
            disabled={loading}
            onClick={() => handleDecision("stop")}
          >
            <X className="h-3 w-3" />
            <span className="ml-1">Stop here</span>
          </Button>
        </div>
      )}
    </div>
  )
}
