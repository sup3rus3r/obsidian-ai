"use client"

import { useRef, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiClient } from "@/lib/api-client"
import { toast } from "sonner"
import type { Agent, N8nImportResponse, N8nImportWarning, WorkflowStep } from "@/types/playground"
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CheckCircle2,
  Download,
  Info,
  Loader2,
  UserX,
} from "lucide-react"

interface N8nImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agents: Agent[]
  onImported: () => void
}

const NODE_TYPE_LABEL: Record<string, string> = {
  start: "Start",
  agent: "Agent",
  condition: "Condition",
  map: "Map",
  approval: "Approval",
  end: "End",
}

const NODE_TYPE_CLASS: Record<string, string> = {
  start: "text-emerald-500 border-emerald-500/40",
  agent: "text-blue-500 border-blue-500/40",
  condition: "text-amber-500 border-amber-500/40",
  map: "text-violet-500 border-violet-500/40",
  approval: "text-orange-500 border-orange-500/40",
  end: "text-muted-foreground border-border",
}

function stepCounts(steps: WorkflowStep[]): [string, number][] {
  const counts = new Map<string, number>()
  for (const step of steps) {
    const key = step.node_type || "agent"
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  return [...counts.entries()]
}

function WarningRow({ warning }: { warning: N8nImportWarning }) {
  const isWarning = warning.level === "warning"
  return (
    <div className="flex gap-2 py-1.5 border-b border-border/50 last:border-0">
      {isWarning ? (
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
      ) : (
        <Info className="h-3.5 w-3.5 text-muted-foreground shrink-0 mt-0.5" />
      )}
      <div className="min-w-0 text-xs">
        {warning.node && (
          <span className="font-mono text-foreground/90">{warning.node}: </span>
        )}
        <span className="text-muted-foreground">{warning.message}</span>
      </div>
    </div>
  )
}

export function N8nImportDialog({ open, onOpenChange, agents, onImported }: N8nImportDialogProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [raw, setRaw] = useState("")
  const [sourceLabel, setSourceLabel] = useState("")
  const [name, setName] = useState("")
  const [defaultAgentId, setDefaultAgentId] = useState("")
  const [preview, setPreview] = useState<N8nImportResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const reset = () => {
    setRaw("")
    setSourceLabel("")
    setName("")
    setDefaultAgentId("")
    setPreview(null)
    setError("")
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const close = (isOpen: boolean) => {
    onOpenChange(isOpen)
    if (!isOpen) reset()
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError("")
    setPreview(null)
    try {
      const text = await file.text()
      setRaw(text)
      setSourceLabel(file.name)
      if (!name) {
        try {
          const parsed = JSON.parse(text)
          if (typeof parsed?.name === "string") setName(parsed.name)
        } catch {
          /* the parse error is reported when the import is attempted */
        }
      }
    } catch {
      setError("Could not read that file.")
    }
  }

  /** Parse locally so a malformed paste is caught before a round trip. */
  const parsed = (): Record<string, unknown> | null => {
    if (!raw.trim()) {
      setError("Choose an n8n export file, or paste the workflow JSON.")
      return null
    }
    try {
      const value = JSON.parse(raw)
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        setError("That JSON isn't an n8n workflow object.")
        return null
      }
      return value as Record<string, unknown>
    } catch {
      setError("That isn't valid JSON. Paste the whole export, or the nodes you copied from the n8n canvas.")
      return null
    }
  }

  const run = async (dryRun: boolean) => {
    setError("")
    const workflow = parsed()
    if (!workflow) return

    setBusy(true)
    try {
      const result = await apiClient.importN8nWorkflow({
        workflow,
        name: name.trim() || undefined,
        default_agent_id: defaultAgentId || undefined,
        dry_run: dryRun,
      })
      if (dryRun) {
        setPreview(result)
      } else {
        toast.success(`Imported "${result.name}"`)
        onImported()
        close(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed")
    } finally {
      setBusy(false)
    }
  }

  const warningCount = preview?.warnings.filter((w) => w.level === "warning").length ?? 0
  const infoCount = preview?.warnings.filter((w) => w.level === "info").length ?? 0

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent showFullscreenButton className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import from n8n</DialogTitle>
          <DialogDescription>
            {preview
              ? "Review what the conversion produced before saving it."
              : "Convert an exported n8n workflow into a workflow here. Nothing is saved until you confirm."}
          </DialogDescription>
        </DialogHeader>

        {!preview && (
          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label htmlFor="n8n-file">Workflow export</Label>
              <input
                ref={fileInputRef}
                id="n8n-file"
                type="file"
                accept=".json,application/json"
                onChange={handleFileChange}
                className="block w-full text-sm text-muted-foreground file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border file:border-border file:text-xs file:font-medium file:bg-background hover:file:bg-muted cursor-pointer"
              />
              <p className="text-xs text-muted-foreground">
                In n8n: workflow menu → Download. You can also select nodes on the canvas, copy them, and paste
                below.
              </p>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="n8n-json">
                {sourceLabel ? `Loaded from ${sourceLabel}` : "Or paste the JSON"}
              </Label>
              <Textarea
                id="n8n-json"
                value={raw}
                onChange={(e) => {
                  setRaw(e.target.value)
                  setSourceLabel("")
                  setError("")
                }}
                placeholder='{ "name": "My workflow", "nodes": [...], "connections": {...} }'
                className="font-mono text-xs h-32"
              />
            </div>

            <div className="grid gap-2 sm:grid-cols-2">
              <div className="grid gap-2">
                <Label htmlFor="n8n-name">Name</Label>
                <Input
                  id="n8n-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Taken from the export"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="n8n-agent">Agent for every step</Label>
                <Select value={defaultAgentId} onValueChange={setDefaultAgentId}>
                  <SelectTrigger id="n8n-agent">
                    <SelectValue placeholder="Assign later" />
                  </SelectTrigger>
                  <SelectContent>
                    {agents.map((agent) => (
                      <SelectItem key={agent.id} value={agent.id}>
                        {agent.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  n8n has no agents, so every converted step needs one. You can retarget them per step afterwards.
                </p>
              </div>
            </div>
          </div>
        )}

        {preview && (
          <div className="grid gap-4 py-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-mono">{preview.name}</span>
              {stepCounts(preview.steps).map(([type, count]) => (
                <Badge
                  key={type}
                  variant="outline"
                  className={`text-[10px] px-1.5 py-0 ${NODE_TYPE_CLASS[type] || ""}`}
                >
                  {count} {NODE_TYPE_LABEL[type] || type}
                </Badge>
              ))}
            </div>

            {preview.needs_agent.length > 0 && (
              <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
                <UserX className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
                <div className="text-xs">
                  <p className="font-medium text-foreground">
                    {preview.needs_agent.length} step
                    {preview.needs_agent.length !== 1 ? "s have" : " has"} no agent
                  </p>
                  <p className="text-muted-foreground mt-0.5">
                    They will not run, and opening the workflow in the editor and saving it drops them. Go back and
                    pick an agent, or assign one per step after importing.
                  </p>
                  <p className="font-mono text-muted-foreground mt-1 break-all">
                    {preview.needs_agent.join(", ")}
                  </p>
                </div>
              </div>
            )}

            {preview.schedules.length > 0 && (
              <div className="flex gap-2 rounded-lg border border-border bg-muted/30 p-3">
                <CalendarClock className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                <div className="text-xs">
                  <p className="font-medium text-foreground">This workflow ran on a timer in n8n</p>
                  <p className="text-muted-foreground mt-0.5">
                    Importing does not create a schedule. To keep it running, add one from the workflow&apos;s
                    SCHEDULE dialog:{" "}
                    {preview.schedules.map((s) => (
                      <code key={s.cron_expr} className="font-mono text-foreground/90">
                        {s.cron_expr}
                      </code>
                    ))}
                  </p>
                </div>
              </div>
            )}

            <div className="grid gap-1 max-h-56 overflow-y-auto rounded-lg border border-border p-3">
              {preview.steps.map((step) => (
                <div key={step.id} className="flex items-start gap-2 text-xs py-1">
                  <Badge
                    variant="outline"
                    className={`text-[10px] px-1.5 py-0 shrink-0 ${NODE_TYPE_CLASS[step.node_type || "agent"] || ""}`}
                  >
                    {NODE_TYPE_LABEL[step.node_type || "agent"] || step.node_type}
                  </Badge>
                  <div className="min-w-0">
                    <span className="font-mono text-foreground/90">{step.id}</span>
                    {step.input_branch && (
                      <span className="ml-1.5 text-amber-500 font-mono">[{step.input_branch}]</span>
                    )}
                    {step.task && (
                      <p className="text-muted-foreground line-clamp-2 mt-0.5">{step.task}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {preview.warnings.length > 0 && (
              <div className="grid gap-1">
                <div className="flex items-center gap-2">
                  <Label className="text-xs">Conversion notes</Label>
                  {warningCount > 0 && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-amber-500 border-amber-500/40">
                      {warningCount} to check
                    </Badge>
                  )}
                  {infoCount > 0 && (
                    <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                      {infoCount} informational
                    </Badge>
                  )}
                </div>
                <div className="max-h-48 overflow-y-auto rounded-lg border border-border px-3">
                  {[...preview.warnings]
                    .sort((a, b) => (a.level === b.level ? 0 : a.level === "warning" ? -1 : 1))
                    .map((warning, i) => (
                      <WarningRow key={`${warning.code}-${warning.node}-${i}`} warning={warning} />
                    ))}
                </div>
              </div>
            )}

            {preview.warnings.length === 0 && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                Everything converted without a note.
              </div>
            )}
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex justify-end gap-2">
          {preview ? (
            <>
              <Button variant="outline" onClick={() => setPreview(null)} disabled={busy}>
                <ArrowLeft className="h-3.5 w-3.5" />
                Back
              </Button>
              <Button onClick={() => run(false)} disabled={busy}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                Import {preview.steps.length} step{preview.steps.length !== 1 ? "s" : ""}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" onClick={() => close(false)} disabled={busy}>
                Cancel
              </Button>
              <Button onClick={() => run(true)} disabled={busy || !raw.trim()}>
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Preview
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
