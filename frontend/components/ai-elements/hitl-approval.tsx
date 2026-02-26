"use client"

import { useState } from "react"
import { ShieldAlert, Check, X, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AppRoutes } from "@/app/api/routes"
import type { HITLApprovalEvent } from "@/types/playground"

interface HITLApprovalProps {
  event: HITLApprovalEvent
  accessToken: string
  onResolved: (status: "approved" | "denied") => void
}

export function HITLApproval({ event, accessToken, onResolved }: HITLApprovalProps) {
  const [loading, setLoading] = useState(false)
  const [resolved, setResolved] = useState<"approved" | "denied" | null>(null)

  const handleDecision = async (decision: "approve" | "reject") => {
    setLoading(true)
    try {
      const url =
        decision === "approve"
          ? AppRoutes.HITLApprove(event.session_id, event.approval_id)
          : AppRoutes.HITLReject(event.session_id, event.approval_id)
      await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const status = decision === "approve" ? "approved" : "denied"
      setResolved(status)
      onResolved(status)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const hasArgs = Object.keys(event.tool_arguments ?? {}).length > 0

  return (
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-4 w-4 text-amber-500 shrink-0" />
        <span className="text-xs font-medium text-amber-600 dark:text-amber-400">Approval Required</span>
      </div>

      <div className="text-xs">
        <span className="font-semibold text-foreground">{event.tool_name}</span>
        {hasArgs && (
          <pre className="mt-1.5 text-xs text-muted-foreground bg-muted/50 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
            {JSON.stringify(event.tool_arguments, null, 2)}
          </pre>
        )}
      </div>

      {resolved ? (
        <div
          className={`flex items-center gap-1.5 text-xs font-medium ${
            resolved === "approved" ? "text-emerald-500" : "text-destructive"
          }`}
        >
          {resolved === "approved" ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
          {resolved === "approved" ? "Approved" : "Denied"}
        </div>
      ) : (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs border-emerald-500/50 text-emerald-600 hover:bg-emerald-500/10 hover:border-emerald-500"
            disabled={loading}
            onClick={() => handleDecision("approve")}
          >
            {loading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Check className="h-3 w-3" />
            )}
            <span className="ml-1">Approve</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs border-destructive/50 text-destructive hover:bg-destructive/10 hover:border-destructive"
            disabled={loading}
            onClick={() => handleDecision("reject")}
          >
            <X className="h-3 w-3" />
            <span className="ml-1">Deny</span>
          </Button>
        </div>
      )}
    </div>
  )
}
