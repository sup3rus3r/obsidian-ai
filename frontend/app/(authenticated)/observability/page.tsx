"use client"

import { useEffect, useState, useCallback } from "react"
import { apiClient } from "@/lib/api-client"
import type {
  AnalyticsOverview,
  TokenBucket,
  LatencyBucket,
  ToolStat,
  CostByAgent,
} from "@/types/playground"
import { Brain, Wrench, Clock, DollarSign, Zap, TrendingUp, AlertCircle, RefreshCw } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`
  return String(n)
}

function fmtCost(usd: number): string {
  if (usd === 0) return "$0.00"
  if (usd < 0.001) return `$${usd.toFixed(6)}`
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtPct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`
}

// ─── Stat Card ───────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  accent,
}: {
  label: string
  value: string
  sub?: string
  icon: React.ElementType
  accent?: string
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">{label}</span>
        <Icon className={`h-4 w-4 ${accent ?? "text-muted-foreground"}`} />
      </div>
      <p className="text-2xl font-semibold">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

// ─── Token Bar Chart ─────────────────────────────────────────────────────────

function TokenTimeline({ buckets }: { buckets: TokenBucket[] }) {
  if (!buckets.length) return <EmptyState label="No LLM calls in this period" />
  const maxTotal = Math.max(...buckets.map(b => b.input_tokens + b.output_tokens), 1)

  return (
    <div className="space-y-1">
      {buckets.map((b) => {
        const total = b.input_tokens + b.output_tokens
        const inputPct = (b.input_tokens / maxTotal) * 100
        const outputPct = (b.output_tokens / maxTotal) * 100
        return (
          <div key={b.date} className="flex items-center gap-3 text-xs">
            <span className="w-20 shrink-0 text-muted-foreground">{b.date.slice(5)}</span>
            <div className="flex-1 flex gap-0.5 h-4 rounded overflow-hidden bg-muted/30">
              <div className="bg-violet-500/70 rounded-l" style={{ width: `${inputPct}%` }} />
              <div className="bg-emerald-500/70 rounded-r" style={{ width: `${outputPct}%` }} />
            </div>
            <span className="w-14 text-right text-muted-foreground">{fmtNumber(total)}</span>
            <span className="w-14 text-right text-amber-600">{fmtCost(b.cost_usd)}</span>
          </div>
        )
      })}
      <div className="flex gap-4 pt-2 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-violet-500/70 inline-block" /> Input</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-emerald-500/70 inline-block" /> Output</span>
      </div>
    </div>
  )
}

// ─── Latency Table ───────────────────────────────────────────────────────────

function LatencyTable({ models }: { models: LatencyBucket[] }) {
  if (!models.length) return <EmptyState label="No LLM calls in this period" />
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-muted-foreground border-b border-border">
          <th className="text-left pb-2 font-medium">Model</th>
          <th className="text-right pb-2 font-medium">Calls</th>
          <th className="text-right pb-2 font-medium">Avg</th>
          <th className="text-right pb-2 font-medium">p50</th>
          <th className="text-right pb-2 font-medium">p95</th>
        </tr>
      </thead>
      <tbody>
        {models.map((m) => (
          <tr key={m.model} className="border-b border-border/50 last:border-0">
            <td className="py-2 font-mono truncate max-w-[160px]">{m.model}</td>
            <td className="py-2 text-right text-muted-foreground">{m.call_count}</td>
            <td className="py-2 text-right">{fmtMs(m.avg_ms)}</td>
            <td className="py-2 text-right text-muted-foreground">{fmtMs(m.p50_ms)}</td>
            <td className={`py-2 text-right ${m.p95_ms > 10000 ? "text-amber-500" : "text-muted-foreground"}`}>{fmtMs(m.p95_ms)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ─── Tool Stats ───────────────────────────────────────────────────────────────

function ToolStatsTable({ tools }: { tools: ToolStat[] }) {
  if (!tools.length) return <EmptyState label="No tool calls in this period" />
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-muted-foreground border-b border-border">
          <th className="text-left pb-2 font-medium">Tool</th>
          <th className="text-right pb-2 font-medium">Calls</th>
          <th className="text-right pb-2 font-medium">Errors</th>
          <th className="text-right pb-2 font-medium">Err Rate</th>
          <th className="text-right pb-2 font-medium">Avg Time</th>
        </tr>
      </thead>
      <tbody>
        {tools.map((t) => (
          <tr key={t.name} className="border-b border-border/50 last:border-0">
            <td className="py-2 font-mono truncate max-w-[160px]">{t.name}</td>
            <td className="py-2 text-right text-muted-foreground">{t.call_count}</td>
            <td className="py-2 text-right text-muted-foreground">{t.error_count}</td>
            <td className={`py-2 text-right ${t.error_rate > 0.1 ? "text-destructive" : t.error_rate > 0 ? "text-amber-500" : "text-muted-foreground"}`}>
              {fmtPct(t.error_rate)}
            </td>
            <td className="py-2 text-right">{fmtMs(t.avg_duration_ms)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ─── Cost by Agent ────────────────────────────────────────────────────────────

function CostByAgentTable({ agents }: { agents: CostByAgent[] }) {
  if (!agents.length) return <EmptyState label="No cost data in this period" />
  const maxCost = Math.max(...agents.map(a => a.total_cost_usd), 0.000001)
  return (
    <div className="space-y-2">
      {agents.map((a, i) => {
        const barPct = (a.total_cost_usd / maxCost) * 100
        return (
          <div key={i} className="flex items-center gap-3 text-xs">
            <span className="w-32 shrink-0 truncate">{a.agent_name ?? "Unknown"}</span>
            <div className="flex-1 h-3 bg-muted/30 rounded overflow-hidden">
              <div className="h-full bg-amber-500/70 rounded" style={{ width: `${barPct}%` }} />
            </div>
            <span className="w-20 text-right font-medium">{fmtCost(a.total_cost_usd)}</span>
            <span className="w-20 text-right text-muted-foreground">
              {fmtNumber(a.total_input_tokens + a.total_output_tokens)} tok
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ─── Empty State ─────────────────────────────────────────────────────────────

function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-24 text-sm text-muted-foreground">
      {label}
    </div>
  )
}

// ─── Section Card ────────────────────────────────────────────────────────────

function Section({ title, icon: Icon, children }: { title: string; icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold mb-4">
        <Icon className="h-4 w-4 text-muted-foreground" />
        {title}
      </h2>
      {children}
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

const RANGE_OPTIONS = [
  { label: "Last 7 days", value: 7 },
  { label: "Last 30 days", value: 30 },
  { label: "Last 90 days", value: 90 },
]

export default function ObservabilityPage() {
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [overview, setOverview] = useState<AnalyticsOverview | null>(null)
  const [tokens, setTokens] = useState<TokenBucket[]>([])
  const [latency, setLatency] = useState<LatencyBucket[]>([])
  const [tools, setTools] = useState<ToolStat[]>([])
  const [cost, setCost] = useState<CostByAgent[]>([])

  const load = useCallback(async (rangeDays: number) => {
    setLoading(true)
    setError(null)
    try {
      const [ovRes, tokRes, latRes, toolRes, costRes] = await Promise.all([
        apiClient.getAnalyticsOverview(rangeDays),
        apiClient.getAnalyticsTokens(rangeDays),
        apiClient.getAnalyticsLatency(rangeDays),
        apiClient.getAnalyticsTools(rangeDays),
        apiClient.getAnalyticsCost(rangeDays),
      ])
      setOverview(ovRes.overview)
      setTokens(tokRes.buckets)
      setLatency(latRes.models)
      setTools(toolRes.tools)
      setCost(costRes.agents)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(days)
  }, [days, load])

  return (
    <div className="flex flex-col h-full overflow-auto">
      <div className="px-6 py-4 border-b border-border flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-lg font-semibold">Observability</h1>
          <p className="text-xs text-muted-foreground mt-0.5">Token usage, latency, cost, and tool analytics</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={String(days)} onValueChange={(v) => setDays(Number(v))}>
            <SelectTrigger className="w-36 h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RANGE_OPTIONS.map((o) => (
                <SelectItem key={o.value} value={String(o.value)} className="text-xs">
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <button
            onClick={() => load(days)}
            disabled={loading}
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border hover:bg-muted/50 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-6 mt-4 p-3 rounded-md bg-destructive/10 border border-destructive/30 flex items-center gap-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="flex-1 px-6 py-4 space-y-5">
        {/* Overview stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            label="Sessions"
            value={fmtNumber(overview?.total_sessions ?? 0)}
            icon={Brain}
          />
          <StatCard
            label="LLM Calls"
            value={fmtNumber(overview?.total_llm_calls ?? 0)}
            sub={`${fmtNumber(overview?.total_tool_calls ?? 0)} tool calls`}
            icon={Zap}
            accent="text-violet-500"
          />
          <StatCard
            label="Total Tokens"
            value={fmtNumber((overview?.total_input_tokens ?? 0) + (overview?.total_output_tokens ?? 0))}
            sub={`${fmtNumber(overview?.total_input_tokens ?? 0)} in / ${fmtNumber(overview?.total_output_tokens ?? 0)} out`}
            icon={TrendingUp}
            accent="text-emerald-500"
          />
          <StatCard
            label="Est. Cost"
            value={fmtCost(overview?.total_cost_usd ?? 0)}
            sub={`Avg ${fmtMs(overview?.avg_latency_ms ?? 0)} / call`}
            icon={DollarSign}
            accent="text-amber-500"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {/* Tokens over time */}
          <Section title="Tokens & Cost Over Time" icon={Zap}>
            <TokenTimeline buckets={tokens} />
          </Section>

          {/* Latency by model */}
          <Section title="Latency by Model" icon={Clock}>
            <LatencyTable models={latency} />
          </Section>

          {/* Tool stats */}
          <Section title="Tool Performance" icon={Wrench}>
            <ToolStatsTable tools={tools} />
          </Section>

          {/* Cost by agent */}
          <Section title="Cost by Agent" icon={DollarSign}>
            <CostByAgentTable agents={cost} />
          </Section>
        </div>

        {overview && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <Badge variant="outline" className="text-[10px]">
              Error rate: {fmtPct(overview.error_rate)}
            </Badge>
            <span>·</span>
            <span>Last {days} days</span>
          </div>
        )}
      </div>
    </div>
  )
}
