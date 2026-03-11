"use client"

import { useEffect, useState, useRef } from "react"
import { useSession } from "next-auth/react"
import { apiClient } from "@/lib/api-client"
import type { Agent, EvalSuite, EvalRun, EvalTestCase } from "@/types/playground"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  FlaskConical,
  Plus,
  Trash2,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  RefreshCw,
} from "lucide-react"
import { toast } from "sonner"

function formatDate(d: string) {
  return new Date(d).toLocaleString()
}

function ScoreBadge({ score, total, passed }: { score: number | null; total: number; passed: number }) {
  if (score === null) return null
  const pct = Math.round(score * 100)
  const allPassed = passed === total
  const color = allPassed ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
    : pct >= 50 ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
    : "bg-red-500/15 text-red-600 dark:text-red-400"
  const label = allPassed ? "PASS" : "FAIL"
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${color}`}>
      {label} · {passed}/{total} ({pct}%)
    </span>
  )
}

function StatusBadge({ status }: { status: EvalRun["status"] }) {
  const map: Record<EvalRun["status"], string> = {
    pending: "bg-muted text-muted-foreground",
    running: "bg-blue-500/15 text-blue-500",
    completed: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
    failed: "bg-red-500/15 text-red-500",
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${map[status]}`}>
      {status}
    </span>
  )
}

// ─── Run results panel ────────────────────────────────────────────────────────

function RunResultsPanel({ run, onClose }: { run: EvalRun; onClose: () => void }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-background border border-border rounded-lg shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-3">
            <FlaskConical className="h-4 w-4 text-blue-500" />
            <span className="font-medium text-sm">Run Results</span>
            <StatusBadge status={run.status} />
            {run.score !== null && (
              <ScoreBadge score={run.score} total={run.total_cases} passed={run.passed_cases} />
            )}
          </div>
          <button type="button" onClick={onClose} className="text-xs text-muted-foreground hover:text-foreground">Close</button>
        </div>
        <div className="overflow-y-auto flex-1 p-4 space-y-2">
          {(!run.results || run.results.length === 0) && (
            <p className="text-sm text-muted-foreground italic">
              {run.status === "running" || run.status === "pending" ? "Run in progress…" : "No results."}
            </p>
          )}
          {run.results?.map((res) => (
            <div key={res.case_id} className={`border rounded-lg overflow-hidden ${res.passed ? "border-emerald-500/20" : "border-red-500/20"}`}>
              <button
                type="button"
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-left hover:bg-muted/30 transition-colors"
                onClick={() => setExpanded(expanded === res.case_id ? null : res.case_id)}
              >
                {res.passed
                  ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                  : <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                }
                <span className="flex-1 truncate font-mono">{res.input.slice(0, 80)}{res.input.length > 80 ? "…" : ""}</span>
                <span className={`shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded ${res.passed ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" : "bg-red-500/15 text-red-500"}`}>
                  {res.passed ? "PASS" : "FAIL"} {Math.round(res.score * 100)}%
                </span>
                {expanded === res.case_id ? <ChevronDown className="h-3 w-3 text-muted-foreground" /> : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
              </button>
              {expanded === res.case_id && (
                <div className="border-t border-border/40 px-3 py-2 space-y-2 bg-muted/20">
                  <div>
                    <div className="text-[10px] text-muted-foreground mb-0.5">Input</div>
                    <pre className="text-xs whitespace-pre-wrap break-all">{res.input}</pre>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <div className="text-[10px] text-muted-foreground mb-0.5">Expected</div>
                      <pre className="text-xs whitespace-pre-wrap break-all text-muted-foreground">{res.expected}</pre>
                    </div>
                    <div>
                      <div className="text-[10px] text-muted-foreground mb-0.5">Actual</div>
                      <pre className={`text-xs whitespace-pre-wrap break-all ${res.passed ? "text-emerald-700 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>{res.actual_output}</pre>
                    </div>
                  </div>
                  {res.reasoning && (
                    <div>
                      <div className="text-[10px] text-muted-foreground mb-0.5">Reasoning</div>
                      <p className="text-xs text-muted-foreground italic">{res.reasoning}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── New Suite dialog ─────────────────────────────────────────────────────────

function SuiteDialog({
  open,
  onOpenChange,
  agents,
  suite,
  onSaved,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  agents: Agent[]
  suite?: EvalSuite | null
  onSaved: (s: EvalSuite) => void
}) {
  const isEdit = !!suite
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [agentId, setAgentId] = useState("")
  const [judgeAgentId, setJudgeAgentId] = useState("")
  const [cases, setCases] = useState<EvalTestCase[]>([])
  const [loading, setLoading] = useState(false)

  const hasLlmJudge = cases.some((c) => c.grading_method === "llm_judge")

  useEffect(() => {
    if (!open) return
    if (suite) {
      setName(suite.name)
      setDescription(suite.description || "")
      setAgentId(suite.agent_id ? String(suite.agent_id) : "")
      setJudgeAgentId(suite.judge_agent_id ? String(suite.judge_agent_id) : "")
      setCases(suite.test_cases)
    } else {
      setName(""); setDescription(""); setAgentId(""); setJudgeAgentId(""); setCases([])
    }
  }, [open, suite])

  const addCase = () => {
    setCases((prev) => [...prev, {
      id: crypto.randomUUID(),
      input: "",
      expected_output: "",
      grading_method: "contains",
      weight: 1.0,
    }])
  }

  const updateCase = (idx: number, field: keyof EvalTestCase, value: string | number) => {
    setCases((prev) => prev.map((c, i) => i === idx ? { ...c, [field]: value } : c))
  }

  const removeCase = (idx: number) => {
    setCases((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleSave = async () => {
    if (!name) return
    setLoading(true)
    try {
      const payload = {
        name,
        description: description || undefined,
        agent_id: agentId || undefined,
        judge_agent_id: judgeAgentId || undefined,
        test_cases: cases,
      }
      let saved: EvalSuite
      if (isEdit && suite) {
        saved = await apiClient.updateEvalSuite(String(suite.id), payload)
      } else {
        saved = await apiClient.createEvalSuite(payload)
      }
      onSaved(saved)
      onOpenChange(false)
    } catch (err: any) {
      toast.error(err?.message || "Failed to save suite")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Eval Suite" : "New Eval Suite"}</DialogTitle>
          <DialogDescription>Define test cases to automatically evaluate your agent.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-2">
          <div className="grid gap-2">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="My suite" />
          </div>
          <div className="grid gap-2">
            <Label>Description</Label>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" />
          </div>
          <div className="grid gap-2">
            <Label>Agent (optional)</Label>
            <Select value={agentId || "none"} onValueChange={(v) => setAgentId(v === "none" ? "" : v)}>
              <SelectTrigger>
                <SelectValue placeholder="Select agent…" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                {agents.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {hasLlmJudge && (
            <div className="grid gap-2">
              <Label>
                LLM Judge Agent
                <span className="ml-1.5 text-xs text-muted-foreground font-normal">— which agent grades the responses</span>
              </Label>
              <Select value={judgeAgentId || "none"} onValueChange={(v) => setJudgeAgentId(v === "none" ? "" : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Select judge agent…" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Same as test agent</SelectItem>
                  {agents.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Test cases */}
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>Test Cases ({cases.length})</Label>
              <Button type="button" size="sm" variant="outline" className="h-7 text-xs" onClick={addCase}>
                <Plus className="h-3 w-3 mr-1" />Add
              </Button>
            </div>
            {cases.length === 0 && (
              <p className="text-xs text-muted-foreground italic">No test cases yet. Add one to get started.</p>
            )}
            <div className="space-y-3 max-h-72 overflow-y-auto">
              {cases.map((c, idx) => (
                <div key={c.id} className="border border-border/60 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">Case {idx + 1}</span>
                    <button type="button" onClick={() => removeCase(idx)} className="text-muted-foreground hover:text-destructive transition-colors">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="grid gap-1.5">
                    <Label className="text-xs">Input</Label>
                    <Textarea
                      value={c.input}
                      onChange={(e) => updateCase(idx, "input", e.target.value)}
                      placeholder="User message sent to the agent"
                      rows={2}
                      className="text-xs resize-none"
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label className="text-xs">Expected Output</Label>
                    <Textarea
                      value={c.expected_output}
                      onChange={(e) => updateCase(idx, "expected_output", e.target.value)}
                      placeholder="Expected response or substring"
                      rows={2}
                      className="text-xs resize-none"
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label className="text-xs">Grading Method</Label>
                    <Select value={c.grading_method} onValueChange={(v) => updateCase(idx, "grading_method", v)}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="contains">Contains</SelectItem>
                        <SelectItem value="exact_match">Exact Match</SelectItem>
                        <SelectItem value="llm_judge">LLM Judge</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={loading || !name}>
            {loading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {isEdit ? "Save Changes" : "Create Suite"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function EvalsPage() {
  const { data: session } = useSession()
  const [suites, setSuites] = useState<EvalSuite[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedSuite, setSelectedSuite] = useState<EvalSuite | null>(null)
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [loadingSuites, setLoadingSuites] = useState(true)
  const [loadingRuns, setLoadingRuns] = useState(false)
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set())
  const [viewRun, setViewRun] = useState<EvalRun | null>(null)
  const [suiteDialogOpen, setSuiteDialogOpen] = useState(false)
  const [editSuite, setEditSuite] = useState<EvalSuite | null>(null)
  const [runAgentId, setRunAgentId] = useState("")
  const pollRef = useRef<NodeJS.Timeout | null>(null)

  // Set token on mount
  useEffect(() => {
    if ((session as any)?.accessToken) {
      apiClient.setAccessToken((session as any).accessToken)
    }
  }, [session])

  useEffect(() => {
    apiClient.listAgents().then(setAgents).catch(() => {})
    loadSuites()
  }, [])

  const loadSuites = async () => {
    setLoadingSuites(true)
    try {
      const list = await apiClient.listEvalSuites()
      setSuites(list)
    } catch {
      toast.error("Failed to load suites")
    } finally {
      setLoadingSuites(false)
    }
  }

  const selectSuite = async (suite: EvalSuite) => {
    setSelectedSuite(suite)
    setRuns([])
    setLoadingRuns(true)
    try {
      const list = await apiClient.listSuiteRuns(String(suite.id))
      setRuns(list)
    } catch {
      // ignore
    } finally {
      setLoadingRuns(false)
    }
  }

  const handleDelete = async (suite: EvalSuite) => {
    try {
      await apiClient.deleteEvalSuite(String(suite.id))
      setSuites((prev) => prev.filter((s) => String(s.id) !== String(suite.id)))
      if (String(selectedSuite?.id) === String(suite.id)) setSelectedSuite(null)
      toast.success("Suite deleted")
    } catch {
      toast.error("Failed to delete suite")
    }
  }

  const handleRun = async () => {
    if (!selectedSuite) return
    const agentId = runAgentId || (selectedSuite.agent_id ? String(selectedSuite.agent_id) : "")
    if (!agentId) {
      toast.error("Select an agent to run against")
      return
    }
    try {
      const run = await apiClient.runEvalSuite(String(selectedSuite.id), { agent_id: agentId })
      setRuns((prev) => [run, ...prev])
      pollRun(String(run.id))
    } catch (err: any) {
      toast.error(err?.message || "Failed to trigger run")
    }
  }

  const pollRun = (runId: string) => {
    setRunningIds((prev) => new Set(prev).add(runId))
    const interval = setInterval(async () => {
      try {
        const updated = await apiClient.getEvalRun(runId)
        setRuns((prev) => prev.map((r) => String(r.id) === runId ? updated : r))
        if (updated.status === "completed" || updated.status === "failed") {
          clearInterval(interval)
          setRunningIds((prev) => { const s = new Set(prev); s.delete(runId); return s })
          if (viewRun && String(viewRun.id) === runId) setViewRun(updated)
        }
      } catch {
        clearInterval(interval)
        setRunningIds((prev) => { const s = new Set(prev); s.delete(runId); return s })
      }
    }, 3000)
  }

  const handleDeleteRun = async (runId: string) => {
    try {
      await apiClient.deleteEvalRun(runId)
      setRuns((prev) => prev.filter((r) => String(r.id) !== runId))
    } catch {
      toast.error("Failed to delete run")
    }
  }

  const agentName = (id: number | string | null) => {
    if (!id) return null
    return agents.find((a) => String(a.id) === String(id))?.name ?? `#${id}`
  }

  return (
    <div className="flex h-full">
      {/* Suite list */}
      <div className="w-72 shrink-0 border-r border-border flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-blue-500" />
            <span className="font-semibold text-sm">Eval Suites</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="h-7 text-xs"
            onClick={() => { setEditSuite(null); setSuiteDialogOpen(true) }}
          >
            <Plus className="h-3 w-3 mr-1" />New
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {loadingSuites && (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}
          {!loadingSuites && suites.length === 0 && (
            <p className="text-xs text-muted-foreground text-center py-8 px-2">
              No eval suites yet. Create one to start evaluating your agents.
            </p>
          )}
          {suites.map((suite) => {
            const isSelected = String(selectedSuite?.id) === String(suite.id)
            return (
              <div
                key={suite.id}
                className={`rounded-lg border p-3 cursor-pointer transition-colors group ${
                  isSelected ? "border-blue-500/40 bg-blue-500/5" : "border-border hover:border-border/80 hover:bg-muted/30"
                }`}
                onClick={() => selectSuite(suite)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{suite.name}</div>
                    {suite.agent_id && (
                      <div className="text-xs text-muted-foreground mt-0.5">{agentName(suite.agent_id)}</div>
                    )}
                    <div className="text-[10px] text-muted-foreground mt-1">
                      {suite.test_cases.length} case{suite.test_cases.length !== 1 ? "s" : ""}
                    </div>
                  </div>
                  <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setEditSuite(suite); setSuiteDialogOpen(true) }}
                      className="text-muted-foreground hover:text-foreground p-0.5"
                    >
                      <RefreshCw className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleDelete(suite) }}
                      className="text-muted-foreground hover:text-destructive p-0.5"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Detail panel */}
      <div className="flex-1 flex flex-col min-w-0">
        {!selectedSuite ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            <div className="text-center space-y-2">
              <FlaskConical className="h-8 w-8 mx-auto opacity-30" />
              <p className="text-sm">Select a suite to view runs and trigger evaluations</p>
            </div>
          </div>
        ) : (
          <>
            {/* Suite header + run controls */}
            <div className="px-6 py-4 border-b border-border">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="font-semibold text-lg">{selectedSuite.name}</h2>
                  {selectedSuite.description && (
                    <p className="text-sm text-muted-foreground mt-0.5">{selectedSuite.description}</p>
                  )}
                  <div className="flex items-center gap-2 mt-1.5">
                    <Badge variant="outline" className="text-xs">{selectedSuite.test_cases.length} test{selectedSuite.test_cases.length !== 1 ? "s" : ""}</Badge>
                    {selectedSuite.agent_id && (
                      <Badge variant="outline" className="text-xs">{agentName(selectedSuite.agent_id)}</Badge>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <Select
                    value={runAgentId || (selectedSuite.agent_id ? String(selectedSuite.agent_id) : "none")}
                    onValueChange={(v) => setRunAgentId(v === "none" ? "" : v)}
                  >
                    <SelectTrigger className="h-8 w-40 text-xs">
                      <SelectValue placeholder="Agent…" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">Select agent…</SelectItem>
                      {agents.map((a) => (
                        <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button size="sm" onClick={handleRun} className="h-8 gap-1.5">
                    <Play className="h-3.5 w-3.5" />
                    Run
                  </Button>
                </div>
              </div>
            </div>

            {/* Runs list */}
            <div className="flex-1 overflow-y-auto p-6">
              <div className="space-y-1.5">
                {loadingRuns && (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                )}
                {!loadingRuns && runs.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-12">
                    No runs yet. Click "Run" to evaluate this suite against an agent.
                  </p>
                )}
                {runs.map((run) => {
                  const isPolling = runningIds.has(String(run.id))
                  return (
                    <div
                      key={run.id}
                      className="flex items-center gap-3 p-3 rounded-lg border border-border hover:bg-muted/30 transition-colors cursor-pointer group"
                      onClick={() => setViewRun(run)}
                    >
                      {isPolling ? (
                        <Loader2 className="h-4 w-4 animate-spin text-blue-500 shrink-0" />
                      ) : run.status === "completed" ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                      ) : run.status === "failed" ? (
                        <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                      ) : (
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <StatusBadge status={run.status} />
                          {run.score !== null && (
                            <ScoreBadge score={run.score} total={run.total_cases} passed={run.passed_cases} />
                          )}
                          {run.agent_id && (
                            <span className="text-xs text-muted-foreground">{agentName(run.agent_id)}</span>
                          )}
                        </div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">{formatDate(run.created_at)}</div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); handleDeleteRun(String(run.id)) }}
                        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all shrink-0"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Modals */}
      <SuiteDialog
        open={suiteDialogOpen}
        onOpenChange={setSuiteDialogOpen}
        agents={agents}
        suite={editSuite}
        onSaved={(saved) => {
          setSuites((prev) => {
            const idx = prev.findIndex((s) => String(s.id) === String(saved.id))
            if (idx >= 0) {
              const next = [...prev]; next[idx] = saved; return next
            }
            return [saved, ...prev]
          })
          toast.success(editSuite ? "Suite updated" : "Suite created")
        }}
      />

      {viewRun && (
        <RunResultsPanel
          run={viewRun}
          onClose={() => setViewRun(null)}
        />
      )}
    </div>
  )
}
