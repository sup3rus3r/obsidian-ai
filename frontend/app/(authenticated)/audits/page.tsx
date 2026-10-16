"use client"

import { useEffect, useState } from "react"
import { apiClient } from "@/lib/api-client"
import type { Agent, AuditRun, AuditProbeResult, AuditProbeCategory } from "@/types/playground"
import { Button } from "@/components/ui/button"
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
  ShieldCheck,
  Play,
  Trash2,
  Loader2,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Wand2,
  Square,
} from "lucide-react"
import { toast } from "sonner"

const IN_PROGRESS_STATUSES: AuditRun["status"][] = ["pending", "generating_probes", "running_probes", "scoring"]

const ALL_CATEGORIES: { value: AuditProbeCategory; label: string; hint: string }[] = [
  { value: "paraphrase", label: "Paraphrase", hint: "Reworded, semantically equivalent prompts" },
  { value: "order", label: "Order", hint: "Reordered facts/options, same content" },
  { value: "adversarial", label: "Adversarial framing", hint: "Same question under pressure/bias" },
  { value: "repeat", label: "Repeated sampling", hint: "Noise-floor control — run this first" },
  { value: "cot_alignment", label: "CoT ↔ action alignment", hint: "Only runs if the model exposes reasoning" },
]

const CONSISTENCY_THRESHOLD = 0.6

function formatDate(d: string) {
  return new Date(d).toLocaleString()
}

function StatusBadge({ status }: { status: AuditRun["status"] }) {
  const map: Record<AuditRun["status"], string> = {
    pending: "bg-muted text-muted-foreground",
    generating_probes: "bg-blue-500/15 text-blue-500",
    running_probes: "bg-blue-500/15 text-blue-500",
    scoring: "bg-blue-500/15 text-blue-500",
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

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return null
  const pct = Math.round(score * 100)
  const color = score >= 0.8 ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
    : score >= CONSISTENCY_THRESHOLD ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
    : "bg-red-500/15 text-red-600 dark:text-red-400"
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${color}`}>
      {pct}% consistent
    </span>
  )
}

// ─── Probe result row ───────────────────────────────────────────────────────

function ProbeRow({ probe }: { probe: AuditProbeResult }) {
  const [open, setOpen] = useState(false)
  const failing = probe.consistency_score < CONSISTENCY_THRESHOLD
  return (
    <div className={`border rounded-lg overflow-hidden ${failing ? "border-red-500/20" : "border-emerald-500/20"}`}>
      <button
        type="button"
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-muted/30 transition-colors cursor-pointer"
        onClick={() => setOpen(!open)}
      >
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground w-28 shrink-0">{probe.category}</span>
        <span className="flex-1 truncate font-mono text-xs">{probe.variant_prompt.slice(0, 70)}{probe.variant_prompt.length > 70 ? "…" : ""}</span>
        <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded ${failing ? "bg-red-500/15 text-red-500" : "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"}`}>
          {Math.round(probe.consistency_score * 100)}%
        </span>
        {open ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
      </button>
      {open && (
        <div className="border-t border-border/40 px-3 py-2 space-y-2 bg-muted/20">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-xs text-muted-foreground mb-0.5">Original prompt</div>
              <pre className="text-xs whitespace-pre-wrap break-all">{probe.original_prompt}</pre>
              <div className="text-xs text-muted-foreground mt-1.5 mb-0.5">Original response</div>
              <pre className="text-xs whitespace-pre-wrap break-all text-muted-foreground">{probe.original_response}</pre>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-0.5">Variant prompt</div>
              <pre className="text-xs whitespace-pre-wrap break-all">{probe.variant_prompt}</pre>
              <div className="text-xs text-muted-foreground mt-1.5 mb-0.5">Variant response</div>
              <pre className={`text-xs whitespace-pre-wrap break-all ${failing ? "text-red-600 dark:text-red-400" : "text-muted-foreground"}`}>{probe.variant_response}</pre>
            </div>
          </div>
          {probe.reasoning && (
            <div>
              <div className="text-xs text-muted-foreground mb-0.5">Judge reasoning{probe.disagreement_type && probe.disagreement_type !== "none" ? ` (${probe.disagreement_type})` : ""}</div>
              <p className="text-xs text-muted-foreground italic">{probe.reasoning}</p>
            </div>
          )}
          {probe.cot_text && (
            <div>
              <div className="text-xs text-muted-foreground mb-0.5 flex items-center gap-1">
                Chain-of-thought {probe.cot_alignment_flag && <span className="text-red-500 font-medium">— mismatch flagged</span>}
              </div>
              <pre className="text-xs whitespace-pre-wrap break-all text-muted-foreground">{probe.cot_text}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Results panel ──────────────────────────────────────────────────────────

function RunResultsPanel({ run, onClose, onSendToOptimizer, onCancel }: { run: AuditRun; onClose: () => void; onSendToOptimizer: (run: AuditRun) => void; onCancel: (run: AuditRun) => void }) {
  const results = run.results || []
  const byCategory = ALL_CATEGORIES.map((c) => ({
    ...c,
    probes: results.filter((r) => r.category === c.value),
    score: run.category_scores?.[c.value],
  })).filter((c) => c.probes.length > 0)

  const lowScore = run.score !== null && run.score !== undefined && run.score < CONSISTENCY_THRESHOLD
  const inProgress = IN_PROGRESS_STATUSES.includes(run.status)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-overlay">
      <div className="bg-background border border-border rounded-xl shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <span className="font-medium text-base">Audit Results</span>
            <StatusBadge status={run.status} />
            <ScoreBadge score={run.score} />
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
          {(!run.results || run.results.length === 0) && (
            <p className="text-sm text-muted-foreground italic">
              {run.status === "completed" ? "No results." : "Run in progress…"}
            </p>
          )}
          {byCategory.find((c) => c.value === "repeat") && (
            <p className="text-xs text-muted-foreground bg-muted/40 rounded-md px-3 py-2">
              Repeated-sampling score is the noise floor — paraphrase/order/adversarial scores should be read
              relative to it, not in isolation. If repeated-sampling consistency is already low, other
              categories' deltas may just be decoding noise, not meaningful sensitivity.
            </p>
          )}
          {byCategory.map((cat) => (
            <div key={cat.value} className="space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold">{cat.label}</span>
                {cat.score !== undefined && <ScoreBadge score={cat.score} />}
              </div>
              <div className="space-y-1.5">
                {cat.probes.map((p, i) => <ProbeRow key={i} probe={p} />)}
              </div>
            </div>
          ))}
        </div>
        {lowScore && run.status === "completed" && (
          <div className="border-t border-border shrink-0 px-4 py-3 flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              This audit found inconsistencies — send these findings to the optimizer as failure signal.
            </p>
            <Button size="sm" onClick={() => onSendToOptimizer(run)}>
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

export default function AuditsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState("")
  const [seedPrompt, setSeedPrompt] = useState("")
  const [categories, setCategories] = useState<Set<AuditProbeCategory>>(new Set(ALL_CATEGORIES.map((c) => c.value)))
  const [probesPerCategory, setProbesPerCategory] = useState(5)
  const [judgeAgentId, setJudgeAgentId] = useState("")
  const [runs, setRuns] = useState<AuditRun[]>([])
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [viewRun, setViewRun] = useState<AuditRun | null>(null)
  const [pollingIds, setPollingIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    apiClient.listAgents().then(setAgents).catch(() => setAgents([]))
  }, [])

  useEffect(() => {
    if (!selectedAgentId) { setRuns([]); return }
    setLoadingRuns(true)
    apiClient.listAgentAuditRuns(selectedAgentId)
      .then(setRuns)
      .catch(() => setRuns([]))
      .finally(() => setLoadingRuns(false))
  }, [selectedAgentId])

  const toggleCategory = (c: AuditProbeCategory) => {
    setCategories((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })
  }

  const pollRun = (runId: string) => {
    setPollingIds((prev) => new Set(prev).add(runId))
    const interval = setInterval(async () => {
      try {
        const updated = await apiClient.getAuditRun(runId)
        setRuns((prev) => prev.map((r) => String(r.id) === runId ? updated : r))
        if (viewRun && String(viewRun.id) === runId) setViewRun(updated)
        if (updated.status === "completed" || updated.status === "failed") {
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
    if (!selectedAgentId || !seedPrompt.trim() || categories.size === 0) return
    setTriggering(true)
    try {
      const run = await apiClient.triggerAudit({
        agent_id: selectedAgentId,
        seed_prompt: seedPrompt.trim(),
        probe_categories: Array.from(categories),
        probes_per_category: probesPerCategory,
        judge_agent_id: judgeAgentId || undefined,
      })
      setRuns((prev) => [run, ...prev])
      pollRun(String(run.id))
      setSeedPrompt("")
    } catch (err: any) {
      toast.error(err?.message || "Failed to trigger audit")
    } finally {
      setTriggering(false)
    }
  }

  const handleDelete = async (runId: string) => {
    try {
      await apiClient.deleteAuditRun(runId)
      setRuns((prev) => prev.filter((r) => String(r.id) !== runId))
    } catch {
      toast.error("Failed to delete run")
    }
  }

  const handleSendToOptimizer = async (run: AuditRun) => {
    try {
      await apiClient.triggerOptimizationFromAudit(String(run.id))
      toast.success("Optimization run started from this audit's findings")
      setViewRun(null)
    } catch (err: any) {
      toast.error(err?.message || "Failed to start optimization")
    }
  }

  const handleCancel = async (run: AuditRun) => {
    try {
      const updated = await apiClient.cancelAuditRun(String(run.id))
      setRuns((prev) => prev.map((r) => String(r.id) === String(run.id) ? updated : r))
      if (viewRun && String(viewRun.id) === String(run.id)) setViewRun(updated)
      toast.success("Audit cancelled")
    } catch (err: any) {
      toast.error(err?.message || "Failed to cancel audit")
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
          <ShieldCheck className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-2xl font-medium tracking-[-0.016em]">Behavioral Audits</h1>
          <p className="text-sm text-muted-foreground">
            Test whether an agent gives consistent answers to equivalent inputs
          </p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
        <div>
          This is black-box behavioral testing, not interpretability. It cannot detect deception, prove
          "understanding," or explain why a model produced an answer — it can only flag that two
          semantically-equivalent inputs produced different outputs, or that a model's stated reasoning
          didn't match its final answer. All scores come from an LLM judge, which is itself fallible. This
          is a signal to investigate, not a verdict — and it is not a safety or jailbreak-resistance test.
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2 items-start">
        <div className="grid gap-4 rounded-xl border border-border p-4">
          <div className="grid gap-2">
            <Label>Agent</Label>
            <Select value={selectedAgentId} onValueChange={setSelectedAgentId}>
              <SelectTrigger>
                <SelectValue placeholder="Select agent to audit…" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label>Seed prompt</Label>
            <Textarea
              value={seedPrompt}
              onChange={(e) => setSeedPrompt(e.target.value)}
              placeholder="A representative question or instruction to probe, e.g. 'Should I invest my savings in index funds?'"
              className="min-h-[70px] text-sm"
            />
          </div>

          <div className="grid gap-2">
            <Label>Probe categories</Label>
            <div className="rounded-md border border-border divide-y divide-border">
              {ALL_CATEGORIES.map((c) => (
                <div key={c.value} className="flex items-center justify-between px-3 py-2">
                  <div>
                    <div className="text-sm">{c.label}</div>
                    <div className="text-[11px] text-muted-foreground">{c.hint}</div>
                  </div>
                  <Switch size="sm" checked={categories.has(c.value)} onCheckedChange={() => toggleCategory(c.value)} />
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-2">
              <Label>Probes per category</Label>
              <Select value={String(probesPerCategory)} onValueChange={(v) => setProbesPerCategory(Number(v))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[3, 5, 8, 10].map((n) => <SelectItem key={n} value={String(n)}>{n}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label>Judge agent (optional)</Label>
              <Select value={judgeAgentId || "none"} onValueChange={(v) => setJudgeAgentId(v === "none" ? "" : v)}>
                <SelectTrigger><SelectValue placeholder="Same as audited agent" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Same as audited agent</SelectItem>
                  {agents.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <Button onClick={handleTrigger} disabled={triggering || !selectedAgentId || !seedPrompt.trim() || categories.size === 0}>
            {triggering ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Play className="h-4 w-4 mr-2" />}
            Run Audit
          </Button>
        </div>

        <div className="space-y-2">
          <Label>Past runs</Label>
          {!selectedAgentId ? (
            <p className="text-sm text-muted-foreground">Select an agent to see its audit history.</p>
          ) : loadingRuns ? (
            <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" /></div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No audits run for this agent yet.</p>
          ) : (
            <div className="rounded-md border border-border divide-y divide-border">
              {runs.map((run) => (
                <div
                  key={run.id}
                  className="flex items-center justify-between px-3 py-2.5 hover:bg-muted/30 cursor-pointer transition-colors"
                  onClick={() => setViewRun(run)}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate">{run.seed_prompt}</div>
                    <div className="text-[11px] text-muted-foreground">{formatDate(run.created_at)}</div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {pollingIds.has(String(run.id)) && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
                    <StatusBadge status={run.status} />
                    <ScoreBadge score={run.score} />
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
