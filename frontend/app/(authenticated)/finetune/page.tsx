"use client"

import { useEffect, useState } from "react"
import { apiClient } from "@/lib/api-client"
import type {
  Agent,
  Session,
  FineTuneRun,
  FineTuneComputeBackend,
  FineTuneHyperparams,
  FineTuneCostEstimate,
  FineTuneDatasetSourceType,
} from "@/types/playground"
import { Routes } from "@/config/routes"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible"
import Link from "next/link"
import {
  Cpu,
  Play,
  Trash2,
  Loader2,
  AlertTriangle,
  Square,
  ChevronDown,
  ChevronRight,
  Download,
  RotateCcw,
} from "lucide-react"
import { toast } from "sonner"

const IN_PROGRESS_STATUSES: FineTuneRun["status"][] = [
  "pending",
  "preparing_dataset",
  "submitting",
  "provisioning",
  "training",
  "merging",
  "converting_gguf",
  "quantizing",
  "registering",
]

const DEFAULT_HYPERPARAMS: FineTuneHyperparams = {
  lora_r: 16,
  lora_alpha: 32,
  lora_dropout: 0.05,
  target_modules: ["q_proj", "v_proj"],
  learning_rate: 2e-4,
  num_epochs: 3,
  per_device_batch_size: 1,
  gradient_accumulation_steps: 8,
  max_seq_len: 1024,
  quantization: "4bit",
  seed: 42,
}

function formatDate(d: string) {
  return new Date(d).toLocaleString()
}

function looksLikeHfRepoId(modelId?: string | null): boolean {
  return !!modelId && modelId.includes("/") && !modelId.includes(" ")
}

function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  const gb = n / 1e9
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  return `${(n / 1e6).toFixed(1)} MB`
}

function StatusBadge({ status }: { status: FineTuneRun["status"] }) {
  const map: Record<FineTuneRun["status"], string> = {
    pending: "bg-muted text-muted-foreground",
    preparing_dataset: "bg-blue-500/15 text-blue-500",
    submitting: "bg-blue-500/15 text-blue-500",
    provisioning: "bg-blue-500/15 text-blue-500",
    training: "bg-blue-500/15 text-blue-500",
    merging: "bg-blue-500/15 text-blue-500",
    converting_gguf: "bg-blue-500/15 text-blue-500",
    quantizing: "bg-blue-500/15 text-blue-500",
    registering: "bg-blue-500/15 text-blue-500",
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

// ─── Results panel ──────────────────────────────────────────────────────────

function RunResultsPanel({
  run,
  onClose,
  onCancel,
  onRetryExport,
}: {
  run: FineTuneRun
  onClose: () => void
  onCancel: (run: FineTuneRun) => void
  onRetryExport: (run: FineTuneRun) => void
}) {
  const inProgress = IN_PROGRESS_STATUSES.includes(run.status)
  const progress = run.progress

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay">
      <div className="bg-background border border-border rounded-xl shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <Cpu className="h-4 w-4 text-primary" />
            <span className="font-medium text-base">Fine-Tune Run</span>
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
          <div className="text-xs text-muted-foreground space-y-0.5">
            <div><span className="font-medium text-foreground">Model:</span> {run.base_hf_model_id}</div>
            <div><span className="font-medium text-foreground">Backend:</span> {run.compute_backend === "runpod" ? "RunPod (cloud GPU)" : "Local GPU (WSL2)"}</div>
            <div><span className="font-medium text-foreground">Dataset:</span> {run.dataset_source_type === "session_export" ? "Session export" : "Uploaded file"}{run.dataset_row_count !== null ? ` — ${run.dataset_row_count} rows` : ""}{run.dataset_filename ? ` (${run.dataset_filename})` : ""}</div>
            {run.error && <div className="text-red-500 mt-1">{run.error}</div>}
          </div>

          {run.status === "training" && progress && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>
                  Step {progress.current_step ?? "—"} / {progress.total_steps ?? "—"}
                  {progress.current_epoch !== null ? ` · epoch ${progress.current_epoch}/${progress.total_epochs ?? "—"}` : ""}
                </span>
                <span>
                  {progress.loss !== null ? `loss ${progress.loss.toFixed(4)}` : ""}
                  {progress.eta_seconds !== null ? ` · ETA ${Math.ceil(progress.eta_seconds / 60)}m` : ""}
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{
                    width: progress.total_steps && progress.current_step
                      ? `${Math.min(100, (progress.current_step / progress.total_steps) * 100)}%`
                      : "0%",
                  }}
                />
              </div>
            </div>
          )}

          <div className="rounded-md border border-border divide-y divide-border text-xs">
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-muted-foreground">Adapter size</span>
              <span>{formatBytes(run.adapter_size_bytes)}</span>
            </div>
            {run.export_to_ollama && (
              <>
                <div className="flex items-center justify-between px-3 py-2">
                  <span className="text-muted-foreground">GGUF size ({run.gguf_quantization})</span>
                  <span>{formatBytes(run.merged_gguf_size_bytes)}</span>
                </div>
                <div className="flex items-center justify-between px-3 py-2">
                  <span className="text-muted-foreground">Ollama model tag</span>
                  <span className="font-mono">{run.ollama_model_tag ?? "—"}</span>
                </div>
              </>
            )}
            {run.compute_backend === "runpod" && (
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">RunPod cost (actual / estimated)</span>
                <span>
                  {run.runpod_actual_cost_usd !== null ? `$${run.runpod_actual_cost_usd.toFixed(2)}` : "—"}
                  {" / "}
                  {run.runpod_estimated_cost_usd !== null ? `$${run.runpod_estimated_cost_usd.toFixed(2)}` : "—"}
                </span>
              </div>
            )}
            {run.created_provider_id && (
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">Registered provider</span>
                <span className="font-mono">{run.created_provider_id}</span>
              </div>
            )}
            {run.created_agent_id && (
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-muted-foreground">Registered agent</span>
                <Link href={`${Routes.DASHBOARD}?agent=${run.created_agent_id}`} className="font-mono text-primary hover:underline">
                  {run.created_agent_id}
                </Link>
              </div>
            )}
          </div>
        </div>
        {run.status === "completed" && (
          <div className="border-t border-border shrink-0 px-4 py-3 flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {run.export_to_ollama && !run.ollama_model_tag
                ? "GGUF export did not complete — you can retry it without re-running training."
                : "Download the trained LoRA adapter."}
            </p>
            <div className="flex items-center gap-2">
              {run.export_to_ollama && !run.ollama_model_tag && (
                <Button size="sm" variant="outline" onClick={() => onRetryExport(run)}>
                  <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
                  Retry export
                </Button>
              )}
              <Button size="sm" variant="outline" onClick={() => apiClient.downloadFinetuneAdapter(String(run.id), run.base_hf_model_id)}>
                <Download className="h-3.5 w-3.5 mr-1.5" />
                Download adapter
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Page ───────────────────────────────────────────────────────────────────

export default function FinetunePage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("")
  const [baseHfModelId, setBaseHfModelId] = useState("")

  const [datasetType, setDatasetType] = useState<FineTuneDatasetSourceType>("session_export")
  const [agentSessions, setAgentSessions] = useState<Session[]>([])
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [selectedSessionIds, setSelectedSessionIds] = useState<Set<string>>(new Set())
  const [uploadedFileData, setUploadedFileData] = useState<string | null>(null)
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null)
  const [datasetRowCount, setDatasetRowCount] = useState<number | undefined>(undefined)

  const [computeBackend, setComputeBackend] = useState<FineTuneComputeBackend>("runpod")
  const [serviceStatus, setServiceStatus] = useState<{ reachable: boolean | null; gpu_available?: boolean; vram_free_gb?: number | null }>({ reachable: null })

  const [hyperparams, setHyperparams] = useState<FineTuneHyperparams>(DEFAULT_HYPERPARAMS)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const [exportToOllama, setExportToOllama] = useState(false)
  const [ggufQuantization, setGgufQuantization] = useState("Q4_K_M")
  const [autoRegisterProvider, setAutoRegisterProvider] = useState(true)
  const [autoRegisterAgent, setAutoRegisterAgent] = useState(true)

  const [costEstimate, setCostEstimate] = useState<FineTuneCostEstimate | null>(null)

  const [runs, setRuns] = useState<FineTuneRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [viewRun, setViewRun] = useState<FineTuneRun | null>(null)
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    apiClient.listAgents().then(setAgents).catch(() => setAgents([]))
  }, [])

  useEffect(() => {
    if (!selectedAgentId) { setRuns([]); return }
    const agent = agents.find((a) => String(a.id) === selectedAgentId)
    if (agent && looksLikeHfRepoId(agent.model_id) && !baseHfModelId) {
      setBaseHfModelId(agent.model_id!)
    }
    setLoadingRuns(true)
    apiClient.listAgentFinetuneRuns(selectedAgentId)
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoadingRuns(false))

    setSelectedSessionIds(new Set())
    setLoadingSessions(true)
    apiClient.listSessionsFiltered("agent", selectedAgentId)
      .then(setAgentSessions)
      .catch(() => setAgentSessions([]))
      .finally(() => setLoadingSessions(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentId])

  useEffect(() => {
    if (!selectedAgentId || runs.length === 0) return
    const anyInProgress = runs.some((r) => IN_PROGRESS_STATUSES.includes(r.status))
    if (!anyInProgress) return
    const interval = setInterval(() => {
      apiClient.listAgentFinetuneRuns(selectedAgentId)
        .then((updated) => {
          setRuns(updated)
          if (viewRun) {
            const match = updated.find((r) => String(r.id) === String(viewRun.id))
            if (match) setViewRun(match)
          }
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentId, runs, viewRun])

  useEffect(() => {
    if (computeBackend !== "local_wsl2") return
    const checkStatus = () => {
      apiClient.getFinetuneServiceStatus()
        .then((s) => setServiceStatus({ reachable: s.reachable, gpu_available: s.gpu_available, vram_free_gb: s.vram_free_gb }))
        .catch(() => setServiceStatus({ reachable: false }))
    }
    checkStatus()
  }, [computeBackend])

  useEffect(() => {
    if (!baseHfModelId.trim()) { setCostEstimate(null); return }
    const timeout = setTimeout(() => {
      apiClient.estimateFinetuneCost({
        base_hf_model_id: baseHfModelId.trim(),
        dataset_row_count: datasetRowCount,
        hyperparams,
        compute_backend: computeBackend,
        export_to_ollama: exportToOllama,
      })
        .then(setCostEstimate)
        .catch(() => setCostEstimate(null))
    }, 500)
    return () => clearTimeout(timeout)
  }, [baseHfModelId, datasetRowCount, hyperparams, computeBackend, exportToOllama])

  const handleFileUpload = (file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      setUploadedFileData(reader.result as string)
      setUploadedFilename(file.name)
    }
    reader.readAsDataURL(file)
  }

  const toggleSession = (id: string) => {
    setSelectedSessionIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const canTrigger = () => {
    if (!selectedAgentId || !baseHfModelId.trim()) return false
    if (datasetType === "session_export") return selectedSessionIds.size > 0
    return !!uploadedFileData
  }

  const handleTrigger = async () => {
    if (!canTrigger()) return
    setTriggering(true)
    try {
      const run = await apiClient.triggerFinetune({
        agent_id: selectedAgentId,
        base_hf_model_id: baseHfModelId.trim(),
        compute_backend: computeBackend,
        dataset: datasetType === "session_export"
          ? { type: "session_export", session_ids: Array.from(selectedSessionIds) }
          : { type: "uploaded_file", file_data: uploadedFileData, filename: uploadedFilename },
        hyperparams,
        export_to_ollama: exportToOllama,
        gguf_quantization: exportToOllama ? ggufQuantization : undefined,
        auto_register_provider: exportToOllama ? autoRegisterProvider : false,
        auto_register_agent: exportToOllama ? autoRegisterAgent : false,
      })
      setRuns((prev) => [run, ...prev])
    } catch (err: any) {
      toast.error(err?.message || "Failed to trigger fine-tune")
    } finally {
      setTriggering(false)
    }
  }

  const handleDelete = async (runId: string) => {
    try {
      await apiClient.deleteFinetuneRun(runId)
      setRuns((prev) => prev.filter((r) => String(r.id) !== runId))
    } catch {
      toast.error("Failed to delete run")
    }
  }

  const handleCancel = async (run: FineTuneRun) => {
    try {
      await apiClient.cancelFinetuneRun(String(run.id))
      const updated = await apiClient.getFinetuneRun(String(run.id))
      setRuns((prev) => prev.map((r) => String(r.id) === String(run.id) ? updated : r))
      if (viewRun && String(viewRun.id) === String(run.id)) setViewRun(updated)
      toast.success("Cancellation requested — this may take a few seconds to take effect")
    } catch (err: any) {
      toast.error(err?.message || "Failed to cancel run")
    }
  }

  const handleRetryExport = async (run: FineTuneRun) => {
    try {
      const updated = await apiClient.retryFinetuneExport(String(run.id))
      setRuns((prev) => prev.map((r) => String(r.id) === String(run.id) ? updated : r))
      setViewRun(updated)
      toast.success("GGUF export retry started")
    } catch (err: any) {
      toast.error(err?.message || "Failed to retry export")
    }
  }

  const setHp = <K extends keyof FineTuneHyperparams>(key: K, value: FineTuneHyperparams[K]) => {
    setHyperparams((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
          <Cpu className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-2xl font-medium tracking-[-0.016em]">LoRA Fine-Tuning</h1>
          <p className="text-sm text-muted-foreground">
            Fine-tune a local model's real HuggingFace weights on your own data
          </p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          Cost and time estimates are rough heuristics based on an assumed model size class, not
          measurements — treat them as ballpark figures, not quotes. Exporting to Ollama/GGUF
          creates a full second copy of the model on disk alongside the LoRA adapter, roughly
          doubling disk usage for that run. Cancelling a run stops the external job but may take a
          few seconds to take effect while the job finishes its current step. RunPod requires a
          pre-configured endpoint (a platform admin setting) and will not work until that's set up.
        </div>
      </div>

      {computeBackend === "local_wsl2" && serviceStatus.reachable === false && (
        <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            Fine-tune service not reachable. It runs as a separate process you start yourself — see
            <code className="font-mono mx-1">backend/finetune_service/README.md</code>
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
            <Label>Base HuggingFace model id or path</Label>
            <Input
              value={baseHfModelId}
              onChange={(e) => setBaseHfModelId(e.target.value)}
              placeholder="e.g. meta-llama/Llama-3.1-8B-Instruct"
              className="font-mono text-sm"
            />
            <p className="text-[11px] text-muted-foreground">
              The real HF checkpoint to fine-tune — not the agent's provider model_id. Required
              because fine-tuning needs direct weight access, which no chat API (including Ollama) exposes.
            </p>
          </div>

          <div className="grid gap-2">
            <Label>Dataset source</Label>
            <Tabs value={datasetType} onValueChange={(v) => setDatasetType(v as FineTuneDatasetSourceType)}>
              <TabsList className="w-full">
                <TabsTrigger value="session_export">Export from sessions</TabsTrigger>
                <TabsTrigger value="uploaded_file">Upload file</TabsTrigger>
              </TabsList>
              <TabsContent value="session_export" className="space-y-2 pt-2">
                <p className="text-[11px] text-muted-foreground">
                  Select the conversations to export as training data for this agent.
                </p>
                {!selectedAgentId ? (
                  <p className="text-xs text-muted-foreground italic">Select an agent first.</p>
                ) : loadingSessions ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Loading sessions…
                  </div>
                ) : agentSessions.length === 0 ? (
                  <p className="text-xs text-muted-foreground italic">This agent has no conversation sessions yet.</p>
                ) : (
                  <>
                    <div className="max-h-48 overflow-y-auto rounded-md border border-border divide-y divide-border">
                      {agentSessions.map((s) => (
                        <label
                          key={s.id}
                          className="flex items-center gap-2 px-2.5 py-1.5 text-xs cursor-pointer hover:bg-muted/50"
                        >
                          <input
                            type="checkbox"
                            checked={selectedSessionIds.has(s.id)}
                            onChange={() => toggleSession(s.id)}
                            className="h-3.5 w-3.5"
                          />
                          <span className="flex-1 truncate">{s.title || `Session ${s.id}`}</span>
                          <span className="text-muted-foreground shrink-0">{formatDate(s.created_at)}</span>
                        </label>
                      ))}
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                      <span>{selectedSessionIds.size} selected</span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className="underline hover:text-foreground"
                          onClick={() => setSelectedSessionIds(new Set(agentSessions.map((s) => s.id)))}
                        >
                          Select all
                        </button>
                        <button
                          type="button"
                          className="underline hover:text-foreground"
                          onClick={() => setSelectedSessionIds(new Set())}
                        >
                          Clear
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </TabsContent>
              <TabsContent value="uploaded_file" className="space-y-2 pt-2">
                <Input
                  type="file"
                  accept=".jsonl,.csv"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) handleFileUpload(file)
                  }}
                />
                {uploadedFilename && (
                  <p className="text-[11px] text-muted-foreground">Selected: {uploadedFilename}</p>
                )}
              </TabsContent>
            </Tabs>
          </div>

          <div className="grid gap-2">
            <Label>Compute backend</Label>
            <Select value={computeBackend} onValueChange={(v) => setComputeBackend(v as FineTuneComputeBackend)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="runpod">RunPod (cloud GPU)</SelectItem>
                <SelectItem value="local_wsl2">Local GPU (WSL2)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {costEstimate && (
            <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-muted-foreground">Estimated time</span>
                <span>{Math.ceil(costEstimate.estimated_minutes)} min</span>
              </div>
              {costEstimate.estimated_usd !== null && (
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Estimated cost</span>
                  <span>${costEstimate.estimated_usd.toFixed(2)}</span>
                </div>
              )}
              <p className="text-muted-foreground italic pt-1">{costEstimate.caveat}</p>
            </div>
          )}

          <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
            <CollapsibleTrigger asChild>
              <button type="button" className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground cursor-pointer">
                {advancedOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                Advanced hyperparameters
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="grid grid-cols-2 gap-3 pt-3">
                <div className="grid gap-1.5">
                  <Label className="text-xs">LoRA rank (r)</Label>
                  <Input type="number" value={hyperparams.lora_r} onChange={(e) => setHp("lora_r", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">LoRA alpha</Label>
                  <Input type="number" value={hyperparams.lora_alpha} onChange={(e) => setHp("lora_alpha", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">LoRA dropout</Label>
                  <Input type="number" step="0.01" value={hyperparams.lora_dropout} onChange={(e) => setHp("lora_dropout", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Target modules</Label>
                  <Input
                    value={(hyperparams.target_modules || []).join(", ")}
                    onChange={(e) => setHp("target_modules", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Learning rate</Label>
                  <Input type="number" step="0.0001" value={hyperparams.learning_rate} onChange={(e) => setHp("learning_rate", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Epochs</Label>
                  <Input type="number" value={hyperparams.num_epochs} onChange={(e) => setHp("num_epochs", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Per-device batch size</Label>
                  <Input type="number" value={hyperparams.per_device_batch_size} onChange={(e) => setHp("per_device_batch_size", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Gradient accumulation steps</Label>
                  <Input type="number" value={hyperparams.gradient_accumulation_steps} onChange={(e) => setHp("gradient_accumulation_steps", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Max sequence length</Label>
                  <Input type="number" value={hyperparams.max_seq_len} onChange={(e) => setHp("max_seq_len", Number(e.target.value))} />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Quantization</Label>
                  <Select value={hyperparams.quantization} onValueChange={(v) => setHp("quantization", v as FineTuneHyperparams["quantization"])}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="4bit">4-bit</SelectItem>
                      <SelectItem value="8bit">8-bit</SelectItem>
                      <SelectItem value="none">None</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Seed</Label>
                  <Input type="number" value={hyperparams.seed} onChange={(e) => setHp("seed", Number(e.target.value))} />
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          <div className="rounded-md border border-border divide-y divide-border">
            <div className="flex items-center justify-between px-3 py-2">
              <div className="text-sm">Export to Ollama</div>
              <Switch size="sm" checked={exportToOllama} onCheckedChange={setExportToOllama} />
            </div>
          </div>

          {exportToOllama && (
            <>
              <div className="grid gap-2">
                <Label>GGUF quantization</Label>
                <Select value={ggufQuantization} onValueChange={setGgufQuantization}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Q4_K_M">Q4_K_M</SelectItem>
                    <SelectItem value="Q5_K_M">Q5_K_M</SelectItem>
                    <SelectItem value="Q8_0">Q8_0</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
                <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                <div>
                  This will create a full second copy of the model on disk, merged with the adapter and
                  quantized for Ollama.
                  {costEstimate?.disk_cost_gb !== null && costEstimate?.disk_cost_gb !== undefined
                    ? ` Expected additional disk usage: ~${costEstimate.disk_cost_gb.toFixed(1)} GB.`
                    : " Expected additional disk usage is model-size dependent."}
                </div>
              </div>

              <div className="rounded-md border border-border divide-y divide-border">
                <div className="flex items-center justify-between px-3 py-2">
                  <div className="text-sm">Auto-register as provider</div>
                  <Switch size="sm" checked={autoRegisterProvider} onCheckedChange={setAutoRegisterProvider} />
                </div>
                <div className="flex items-center justify-between px-3 py-2">
                  <div className="text-sm">Auto-register as agent</div>
                  <Switch size="sm" checked={autoRegisterAgent} onCheckedChange={setAutoRegisterAgent} />
                </div>
              </div>
            </>
          )}

          <Button onClick={handleTrigger} disabled={triggering || !canTrigger()}>
            {triggering ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Play className="h-4 w-4 mr-2" />}
            Start Fine-Tune
          </Button>
        </div>

        <div className="space-y-2">
          <Label>Past runs</Label>
          {!selectedAgentId ? (
            <p className="text-sm text-muted-foreground">Select an agent to see its fine-tune history.</p>
          ) : loadingRuns ? (
            <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No fine-tune runs for this agent yet.</p>
          ) : (
            <div className="rounded-md border border-border divide-y divide-border">
              {runs.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between px-3 py-2.5 hover:bg-muted/30 cursor-pointer transition-colors"
                  onClick={() => setViewRun(run)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-mono truncate">{run.base_hf_model_id}</div>
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
                    {!IN_PROGRESS_STATUSES.includes(run.status) && (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={(e) => { e.stopPropagation(); handleDelete(String(run.id)) }}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {viewRun && (
        <RunResultsPanel run={viewRun} onClose={() => setViewRun(null)} onCancel={handleCancel} onRetryExport={handleRetryExport} />
      )}
    </div>
  )
}
