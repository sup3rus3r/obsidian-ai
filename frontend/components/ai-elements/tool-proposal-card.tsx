"use client"

import { useState } from "react"
import { Wrench, Sparkles, Check, X, Loader2, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AppRoutes } from "@/app/api/routes"
import type { ToolProposalEvent } from "@/types/playground"

interface ToolProposalCardProps {
  event: ToolProposalEvent
  accessToken: string
  onResolved: (status: "approved" | "rejected") => void
}

export function ToolProposalCard({ event, accessToken, onResolved }: ToolProposalCardProps) {
  const [loading, setLoading] = useState(false)
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(null)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)

  const handleDecision = async (decision: "approve" | "reject") => {
    setLoading(true)
    try {
      const url =
        decision === "approve"
          ? AppRoutes.ToolProposalApprove(event.session_id, event.proposal_id)
          : AppRoutes.ToolProposalReject(event.session_id, event.proposal_id)
      const res = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      })
      const status = decision === "approve" ? "approved" : "rejected"
      setResolved(status)
      if (decision === "approve") {
        const data = await res.json().catch(() => ({}))
        window.dispatchEvent(new CustomEvent("tool-created", { detail: { toolId: data.tool_id } }))
      }
      onResolved(status)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  const hasParams = Object.keys(event.parameters ?? {}).length > 0
  const hasConfig = event.handler_config && Object.keys(event.handler_config).length > 0

  return (
    <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 space-y-2.5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1">
          <Wrench className="h-3.5 w-3.5 text-violet-500 shrink-0" />
          <Sparkles className="h-3 w-3 text-violet-400 shrink-0" />
        </div>
        <span className="text-xs font-medium text-violet-600 dark:text-violet-400">Tool Proposal</span>
        <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-600 dark:text-violet-300 font-mono">
          {event.handler_type}
        </span>
      </div>

      {/* Tool name + description */}
      <div className="space-y-1">
        <div className="font-mono text-xs font-semibold text-foreground">{event.name}</div>
        {event.description && (
          <div className="text-xs text-muted-foreground">{event.description}</div>
        )}
      </div>

      {/* Parameters collapsible */}
      {hasParams && (
        <div className="border border-border/40 rounded overflow-hidden">
          <button
            className="flex items-center gap-1.5 w-full px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted/30 transition-colors"
            onClick={() => setParamsOpen((o) => !o)}
          >
            {paramsOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            Parameters
          </button>
          {paramsOpen && (
            <pre className="text-xs text-muted-foreground bg-muted/30 px-2 py-1.5 overflow-x-auto whitespace-pre-wrap break-all border-t border-border/40">
              {JSON.stringify(event.parameters, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Handler config collapsible */}
      {hasConfig && (
        <div className="border border-border/40 rounded overflow-hidden">
          <button
            className="flex items-center gap-1.5 w-full px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted/30 transition-colors"
            onClick={() => setConfigOpen((o) => !o)}
          >
            {configOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {event.handler_type === "python" ? "Python Code" : "HTTP Config"}
          </button>
          {configOpen && (
            <pre className="text-xs text-muted-foreground bg-muted/30 px-2 py-1.5 overflow-x-auto whitespace-pre-wrap break-all border-t border-border/40">
              {event.handler_type === "python"
                ? String((event.handler_config as Record<string, unknown>)?.code ?? JSON.stringify(event.handler_config, null, 2))
                : JSON.stringify(event.handler_config, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Warning */}
      {!resolved && (
        <div className="flex items-start gap-1.5 text-[10px] text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
          <span>Approving will save this tool to your global toolkit.</span>
        </div>
      )}

      {/* Actions / resolved state */}
      {resolved ? (
        <div
          className={`flex items-center gap-1.5 text-xs font-medium ${
            resolved === "approved" ? "text-emerald-500" : "text-destructive"
          }`}
        >
          {resolved === "approved" ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
          {resolved === "approved" ? "Saved & enabled" : "Rejected"}
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
            {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
            <span className="ml-1">Save & Enable</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-7 px-2.5 text-xs border-destructive/50 text-destructive hover:bg-destructive/10 hover:border-destructive"
            disabled={loading}
            onClick={() => handleDecision("reject")}
          >
            <X className="h-3 w-3" />
            <span className="ml-1">Reject</span>
          </Button>
        </div>
      )}
    </div>
  )
}
