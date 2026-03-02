"use client"

import { useState } from "react"
import { Wrench, Sparkles, Check, X, Loader2, ChevronDown, ChevronRight, AlertTriangle, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { AppRoutes } from "@/app/api/routes"
import type { ToolProposalEvent } from "@/types/playground"

interface ToolProposalCardProps {
  event: ToolProposalEvent
  accessToken: string
  onResolved: (status: "approved" | "rejected") => void
}

function InlineDiff({ label, before, after }: { label: string; before: string; after: string }) {
  const [open, setOpen] = useState(false)
  if (before === after) return null
  return (
    <div className="border border-border/40 rounded overflow-hidden">
      <button
        className="flex items-center gap-1.5 w-full px-2 py-1.5 text-xs text-muted-foreground hover:bg-muted/30 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {label}
        <span className="ml-auto text-[10px] text-amber-500 font-medium">changed</span>
      </button>
      {open && (
        <div className="border-t border-border/40 grid grid-cols-2 divide-x divide-border/40 text-[10px] font-mono">
          <div className="px-2 py-1.5 bg-red-500/5 overflow-x-auto whitespace-pre-wrap break-all text-red-600 dark:text-red-400">
            <div className="text-[9px] text-muted-foreground mb-1 font-sans">Before</div>
            {before}
          </div>
          <div className="px-2 py-1.5 bg-emerald-500/5 overflow-x-auto whitespace-pre-wrap break-all text-emerald-700 dark:text-emerald-400">
            <div className="text-[9px] text-muted-foreground mb-1 font-sans">After</div>
            {after}
          </div>
        </div>
      )}
    </div>
  )
}

export function ToolProposalCard({ event, accessToken, onResolved }: ToolProposalCardProps) {
  const [loading, setLoading] = useState(false)
  const [resolved, setResolved] = useState<"approved" | "rejected" | null>(null)
  const [paramsOpen, setParamsOpen] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)

  const isEdit = event.proposal_type === "edit"

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

  // For diff display
  const existingParamsStr = event.existing_parameters ? JSON.stringify(event.existing_parameters, null, 2) : ""
  const newParamsStr = JSON.stringify(event.parameters ?? {}, null, 2)
  const existingConfigStr = event.existing_handler_config
    ? (event.existing_handler_config as Record<string, unknown>)?.code
      ? String((event.existing_handler_config as Record<string, unknown>).code)
      : JSON.stringify(event.existing_handler_config, null, 2)
    : ""
  const newConfigStr = event.handler_config
    ? (event.handler_config as Record<string, unknown>)?.code
      ? String((event.handler_config as Record<string, unknown>).code)
      : JSON.stringify(event.handler_config, null, 2)
    : ""

  return (
    <div className={`rounded-lg border p-3 space-y-2.5 ${isEdit ? "border-amber-500/30 bg-amber-500/5" : "border-violet-500/30 bg-violet-500/5"}`}>
      {/* Header */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1">
          <Wrench className={`h-3.5 w-3.5 shrink-0 ${isEdit ? "text-amber-500" : "text-violet-500"}`} />
          {isEdit
            ? <Pencil className="h-3 w-3 text-amber-400 shrink-0" />
            : <Sparkles className="h-3 w-3 text-violet-400 shrink-0" />
          }
        </div>
        <span className={`text-xs font-medium ${isEdit ? "text-amber-600 dark:text-amber-400" : "text-violet-600 dark:text-violet-400"}`}>
          {isEdit ? "Tool Edit Proposal" : "Tool Proposal"}
        </span>
        <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded font-mono ${isEdit ? "bg-amber-500/15 text-amber-600 dark:text-amber-300" : "bg-violet-500/15 text-violet-600 dark:text-violet-300"}`}>
          {event.handler_type}
        </span>
      </div>

      {/* Tool name */}
      <div className="space-y-1">
        <div className="font-mono text-xs font-semibold text-foreground">{event.name}</div>
        {isEdit ? (
          /* Edit: show description diff */
          event.existing_description !== event.description && (
            <InlineDiff
              label="Description"
              before={event.existing_description ?? ""}
              after={event.description ?? ""}
            />
          )
        ) : (
          event.description && (
            <div className="text-xs text-muted-foreground">{event.description}</div>
          )
        )}
      </div>

      {isEdit ? (
        /* Edit mode: show diffs for params and handler config */
        <>
          {existingParamsStr !== newParamsStr && (
            <InlineDiff label="Parameters" before={existingParamsStr} after={newParamsStr} />
          )}
          {existingConfigStr !== newConfigStr && (
            <InlineDiff
              label={event.handler_type === "python" ? "Python Code" : "HTTP Config"}
              before={existingConfigStr}
              after={newConfigStr}
            />
          )}
          {existingParamsStr === newParamsStr && existingConfigStr === newConfigStr && event.existing_description === event.description && (
            <p className="text-xs text-muted-foreground italic">No changes detected in this proposal.</p>
          )}
        </>
      ) : (
        /* Create mode: show params and config as before */
        <>
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
        </>
      )}

      {/* Warning */}
      {!resolved && (
        <div className="flex items-start gap-1.5 text-[10px] text-amber-600 dark:text-amber-400">
          <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
          <span>
            {isEdit
              ? "Approving will update the existing tool in your toolkit."
              : "Approving will save this tool to your global toolkit."}
          </span>
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
          {resolved === "approved"
            ? isEdit ? "Updated & applied" : "Saved & enabled"
            : isEdit ? "Edit rejected" : "Rejected"}
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
            <span className="ml-1">{isEdit ? "Apply Changes" : "Save & Enable"}</span>
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
