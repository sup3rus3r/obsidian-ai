"use client"

import { useEffect, useState } from "react"
import { apiClient } from "@/lib/api-client"
import type { Agent, InspectionRun, InspectionLayerSummary } from "@/types/playground"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Microscope,
  Play,
  Trash2,
  Loader2,
  AlertTriangle,
  Wand2,
  Square,
  CircleDot,
} from "lucide-react"
import { toast } from "sonner"

const IN_PROGRESS_STATUSES: InspectionRun["status"][] = ["pending", "loading_model", "capturing", "processing"]

function formatDate(d: string) {
  return new Date(d).toLocaleString()
}

function looksLikeHfRepoId(modelId?: string | null): boolean {
  return !!modelId && modelId.includes("/") && !modelId.includes(" ")
}

function StatusBadge({ status }: { status: InspectionRun["status"] }) {
  const map: Record<InspectionRun["status"], string> = {
    pending: "bg-muted text-muted-foreground",
    loading_model: "bg-blue-500/15 text-blue-500",
    capturing: "bg-blue-500/15 text-blue-500",
    processing: "bg-blue-500/15 text-blue-500",
    completed: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
    failed: "bg-red-500/15 text-red-500",
    cancelled: "bg-muted text-muted-foreground",
  }
  const label = status.replace(/_/g, " ")
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[status]}`}>
      {label}
    </span>
  )
}

// ─── Per-layer row ──────────────────────────────────────────────────────────

function LayerRow({ layer, finalTopToken }: { layer: InspectionLayerSummary; finalTopToken: string | null }) {
  const topToken = layer.logit_lens_top_tokens?.[0]
  const diverges = topToken && finalTopToken && topToken.token !== finalTopToken
  const avgEntropy = layer.attention_entropy_by_head
    ? layer.attention_entropy_by_head.reduce((a, b) => a + b, 0) / layer.attention_entropy_by_head.length
    : null

  return (
    <div className="flex items-center gap-3 px-3 py-2 border-b border-border/40 last:border-0 text-xs">
      <span className="w-14 shrink-0 font-mono text-muted-foreground">layer {layer.layer}</span>
      <div className="flex-1 min-w-0 flex items-center gap-1.5">
        <span className="font-mono truncate">{topToken ? JSON.stringify(topToken.token) : "—"}</span>
        {topToken && <span className="text-muted-foreground shrink-0">({Math.round(topToken.probability * 100)}%)</span>}
        {diverges && (
          <span title="Diverges from final layer's top projection" className="shrink-0">
            <CircleDot className="h-3 w-3 text-amber-500" />
          </span>
        )}
      </div>
      {layer.residual_norm !== null && (
        <span className="w-24 shrink-0 text-muted-foreground">norm {layer.residual_norm.toFixed(2)}</span>
      )}
      {avgEntropy !== null && (
        <span className="w-28 shrink-0 text-muted-foreground">entropy {avgEntropy.toFixed(2)}</span>
      )}
    </div>
  )
}

// ─── Results panel ──────────────────────────────────────────────────────────

function RunResultsPanel({ run, onClose, onSendToOptimizer, onCancel }: { run: InspectionRun; onClose: () => void; onSendToOptimizer: (run: InspectionRun) => void; onCancel: (run: InspectionRun) => void }) {
  const inProgress = IN_PROGRESS_STATUSES.includes(run.status)
  const perLayer = run.summary?.per_layer || []
  const finalTopToken = perLayer.length > 0 ? (perLayer[perLayer.length - 1].logit_lens_top_tokens?.[0]?.token ?? null) : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay">
      <div className="bg-background border border-border rounded-xl shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <Microscope className="h-4 w-4 text-primary" />
            <span className="font-medium text-base">Inspection Results</span>
            <StatusBadge status={run.status} />
          </div>
          <div className="flex items-center gap-3">
            {inProgress && (
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => onCancel(run)}>
                <Square className="h-3 w-3 mr-1.5" />
                Stop
              </Button>
            )}
            <button type="button" onClick={onClose} className="text-sm text-muted-foreground hover:text-foreground cursor-pointer">Close</button>
          </div>
        </div>
        <div className="overflow-y-auto flex-1 p-4 space-y-4">
          <div className="text-xs text-muted-foreground">
            <div><span className="font-medium text-foreground">Model:</span> {run.hf_model_id}</div>
            <div className="truncate"><span className="font-medium text-foreground">Prompt:</span> {run.prompt}</div>
            {run.error && <div className="text-red-500 mt-1">{run.error}</div>}
          </div>

          {run.summary ? (
            <div>
              {run.summary.truncated && (
                <p className="text-xs text-amber-600 dark:text-amber-400 bg-amber-500/10 rounded-md px-3 py-2 mb-2">
                  Prompt was truncated to {run.summary.token_count} tokens for this capture.
                </p>
              )}
              <div className="rounded-md border border-border overflow-hidden">
                {perLayer.map((layer) => (
                  <LayerRow key={layer.layer} layer={layer} finalTopToken={finalTopToken} />
                ))}
              </div>
              <p className="text-[11px] text-muted-foreground mt-2">
                "Diverges" (●) means this layer's top logit-lens projection differs from the final layer's —
                consistent with late-stage revision of an initial leaning, not evidence of what the model "believed."
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">
              {run.status === "completed" ? "No summary data." : "Inspection in progress…"}
            </p>
          )}
        </div>
        {run.status === "completed" && run.summary && (
          <div className="border-t border-border shrink-0 px-4 py-3 flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Send these projections/attention statistics to the optimizer as additional failure-signal context.
            </p>
            <Button size="sm" variant="outline" onClick={() => onSendToOptimizer(run)}>
              <Wand2 className="h-3.5 w-3.5 mr-1.5" />
              Send to Optimizer
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function InspectPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("")
  const [hfModelId, setHfModelId] = useState("")
  const [prompt, setPrompt] = useState("")
  const [captureAttention, setCaptureAttention] = useState(true)
  const [captureResidual, setCaptureResidual] = useState(true)
  const [maxSeqLen, setMaxSeqLen] = useState(256)
  const [runs, setRuns] = useState<InspectionRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [viewRun, setViewRun] = useState<InspectionRun | null>(null)
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set())
  const [serviceReachable, setServiceReachable] = useState<boolean | null>(null)

  useEffect(() => {
    apiClient.listAgents().then(setAgents).catch(() => setAgents([]))
    apiClient.getInspectorStatus()
      .then((s) => setServiceReachable(s.reachable))
      .catch(() => setServiceReachable(false))
  }, [])

  useEffect(() => {
    if (!selectedAgentId) { setRuns([]); return }
    const agent = agents.find((a) => String(a.id) === selectedAgentId)
    if (agent && looksLikeHfRepoId(agent.model_id) && !hfModelId) {
      setHfModelId(agent.model_id!)
    }
    setLoadingRuns(true)
    apiClient.listAgentInspectionRuns(selectedAgentId)
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoadingRuns(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentId])

  const pollRun = (runId: string) => {
    setPollingIds((prev) => new Set(prev).add(runId))
    const interval = setInterval(async () => {
      try {
        const updated = await apiClient.getInspectionRun(runId)
        setRuns((prev) => prev.map((r) => String(r.id) === runId ? updated : r))
        if (viewRun && String(viewRun.id) === runId) setViewRun(updated)
        if (!IN_PROGRESS_STATUSES.includes(updated.status)) {
          clearInterval(interval)
          setPollingIds((prev) => { const s = new Set(prev); s.delete(runId); return s })
        }
      } catch {
        clearInterval(interval)
        setPollingIds((prev) => { const s = new Set(prev); s.delete(runId); return s })
      }
    }, 3000)
  }

  const handleTrigger = async () => {
    if (!selectedAgentId || !hfModelId.trim() || !prompt.trim()) return
    setTriggering(true)
    try {
      const run = await apiClient.triggerInspection({
        agent_id: selectedAgentId,
        hf_model_id: hfModelId.trim(),
        prompt: prompt.trim(),
        capture_config: {
          capture_attention: captureAttention,
          capture_residual: captureResidual,
          max_seq_len: maxSeqLen,
        },
      })
      setRuns((prev) => [run, ...prev])
      pollRun(String(run.id))
    } catch (err: any) {
      toast.error(err?.message || "Failed to trigger inspection")
    } finally {
      setTriggering(false)
    }
  }

  const handleDelete = async (runId: string) => {
    try {
      await apiClient.deleteInspectionRun(runId)
      setRuns((prev) => prev.filter((r) => String(r.id) !== runId))
    } catch {
      toast.error("Failed to delete run")
    }
  }

  const handleCancel = async (run: InspectionRun) => {
    try {
      const updated = await apiClient.cancelInspectionRun(String(run.id))
      setRuns((prev) => prev.map((r) => String(r.id) === String(run.id) ? updated : r))
      if (viewRun && String(viewRun.id) === String(run.id)) setViewRun(updated)
      toast.success("Inspection cancelled")
    } catch (err: any) {
      toast.error(err?.message || "Failed to cancel inspection")
    }
  }

  const handleSendToOptimizer = async (run: InspectionRun) => {
    try {
      await apiClient.triggerOptimizationFromInspection(String(run.id))
      toast.success("Optimization run started from this inspection's findings")
      setViewRun(null)
    } catch (err: any) {
      toast.error(err?.message || "Failed to start optimization")
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
          <Microscope className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-2xl font-medium tracking-[-0.016em]">Model Inspection</h1>
          <p className="text-sm text-muted-foreground">
            Activation, attention, and logit-lens probing for local models
          </p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          This is real inspection tooling, not solved interpretability. Attention weight is not causation —
          it only shows where probability mass was routed on one forward pass. Logit lens is one specific linear
          projection with known basis-drift limitations, not a readout of the model's "belief." Single-neuron
          activations are not presumed interpretable features. A single prompt's run is not a general statement
          about the model, and this is not a safety or deception detector. Only works for models whose real
          HuggingFace weights are reachable — never cloud-provider agents, whose weights never leave their servers.
        </div>
      </div>

      {serviceReachable === false && (
        <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            Inspector service not reachable. It runs as a separate process you start yourself — see
            <code className="font-mono mx-1">backend/inspector_service/README.md</code>
            for setup. The main backend never starts this for you.
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <div className="grid gap-4 rounded-xl border border-border p-4">
          <div className="grid gap-2">
            <Label>Agent</Label>
            <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
              <SelectTrigger>
                <SelectValue placeholder="Select agent…" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label>HuggingFace model id or path</Label>
            <Input
              value={hfModelId}
              onChange={(e) => setHfModelId(e.target.value)}
              placeholder="e.g. meta-llama/Llama-3.1-8B-Instruct"
              className="font-mono text-sm"
            />
            <p className="text-[11px] text-muted-foreground">
              The real HF checkpoint for this model — not the agent's provider model_id. Required
              because inspection needs direct weight access, which no chat API (including Ollama) exposes.
            </p>
          </div>

          <div className="grid gap-2">
            <Label>Prompt</Label>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="A short prompt to inspect — kept brief by default since full activation capture scales with sequence length"
              className="min-h-16.5 text-sm"
            />
          </div>

          <div className="rounded-md border border-border divide-y divide-border">
            <div className="flex items-center justify-between px-3 py-2">
              <div className="text-sm">Capture attention patterns</div>
              <Switch size="sm" checked={captureAttention} onCheckedChange={setCaptureAttention} />
            </div>
            <div className="flex items-center justify-between px-3 py-2">
              <div className="text-sm">Capture residual stream / logit lens</div>
              <Switch size="sm" checked={captureResidual} onCheckedChange={setCaptureResidual} />
            </div>
          </div>

          <div className="grid gap-2">
            <Label>Max sequence length</Label>
            <Select value={String(maxSeqLen)} onValueChange={(v) => setMaxSeqLen(Number(v))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {[128, 256, 512].map((n) => <SelectItem key={n} value={String(n)}>{n} tokens</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          <Button onClick={handleTrigger} disabled={triggering || !selectedAgentId || !hfModelId.trim() || !prompt.trim()}>
            {triggering ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Play className="h-4 w-4 mr-2" />}
            Run Inspection
          </Button>
        </div>

        <div className="space-y-2">
          <Label>Past runs</Label>
          {!selectedAgentId ? (
            <p className="text-sm text-muted-foreground">Select an agent to see its inspection history.</p>
          ) : loadingRuns ? (
            <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No inspections run for this agent yet.</p>
          ) : (
            <div className="rounded-md border border-border divide-y divide-border">
              {runs.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between px-3 py-2.5 hover:bg-muted/30 cursor-pointer transition-colors"
                  onClick={() => setViewRun(run)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate">{run.prompt}</div>
                    <div className="text-[11px] text-muted-foreground font-mono truncate">{run.hf_model_id}</div>
                    <div className="text-[11px] text-muted-foreground">{formatDate(run.created_at)}</div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {pollingIds.has(String(run.id)) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
                    <StatusBadge status={run.status} />
                    {IN_PROGRESS_STATUSES.includes(run.status) && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        title="Stop"
                        onClick={(e) => { e.stopPropagation(); handleCancel(run) }}
                      >
                        <Square className="h-3.5 w-3.5 text-muted-foreground" />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      onClick={(e) => { e.stopPropagation(); handleDelete(String(run.id)) }}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-destructive" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {viewRun && (
        <RunResultsPanel run={viewRun} onClose={() => setViewRun(null)} onSendToOptimizer={handleSendToOptimizer} onCancel={handleCancel} />
      )}
    </div>
  )
}
