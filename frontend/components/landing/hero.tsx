"use client"

import { motion, AnimatePresence } from "motion/react"
import { Button } from "@/components/ui/button"
import {
  ArrowRight,
  Sparkles,
  Bot,
  Workflow,
  MessageSquare,
  CheckCircle,
  Wrench,
  Users,
  Settings,
  Cpu,
  Loader2,
  BookOpen,
  Brain,
  GitBranch,
  Server,
  FileCode2,
  Shield,
  Key,
  Database,
  Github,
} from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"

/* ------------------------------------------------------------------ */
/*  Subtle grid + glow background                                       */
/* ------------------------------------------------------------------ */
function Background() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {/* Fine grid */}
      <div
        className="absolute inset-0 opacity-[0.018]"
        style={{
          backgroundImage: `linear-gradient(to right, hsl(var(--foreground)) 1px, transparent 1px),
                            linear-gradient(to bottom, hsl(var(--foreground)) 1px, transparent 1px)`,
          backgroundSize: "72px 72px",
        }}
      />
      {/* Top-left editorial glow — offset to match left-aligned text */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_45%_at_25%_0%,hsl(var(--foreground)/0.05),transparent)]" />
      {/* Center-right glow near demo */}
      <motion.div
        className="absolute left-2/3 top-1/4 h-96 w-96 -translate-x-1/2 rounded-full bg-foreground/3 blur-[120px]"
        animate={{ opacity: [0.5, 0.9, 0.5] }}
        transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Demo tabs                                                           */
/* ------------------------------------------------------------------ */
function PlaygroundDemo() {
  const [step, setStep] = useState(0)
  useEffect(() => {
    const timers = [
      setTimeout(() => setStep(1), 600),
      setTimeout(() => setStep(2), 1400),
      setTimeout(() => setStep(3), 2200),
    ]
    return () => timers.forEach(clearTimeout)
  }, [])

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-1 overflow-hidden">
        <div className="hidden sm:flex w-40 shrink-0 flex-col border-r border-border/20 bg-muted/5 p-2 gap-0.5">
          <p className="px-2 py-1 text-[9px] font-semibold uppercase tracking-widest text-muted-foreground/40 mb-1">Sessions</p>
          {["Research session", "Code review", "Data analysis"].map((s, i) => (
            <div key={s} className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-[11px] cursor-default ${i === 0 ? "bg-muted/30 text-foreground" : "text-muted-foreground/60"}`}>
              <MessageSquare className="h-3 w-3 shrink-0" /><span className="truncate">{s}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-1 flex-col gap-2 overflow-hidden p-3">
          <motion.div className="flex justify-end" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
            <div className="max-w-[78%] rounded-2xl rounded-tr-sm bg-primary px-3.5 py-2 text-[11px] leading-relaxed text-primary-foreground">
              What&apos;s the weather in Tokyo and summarise today&apos;s AI news?
            </div>
          </motion.div>

          {step >= 1 && (
            <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
              <div className="flex items-center gap-2 rounded-lg border border-border/25 bg-muted/20 px-3 py-1.5 text-[10px]">
                <Wrench className="h-3 w-3 text-muted-foreground/60" />
                <span className="font-mono text-muted-foreground/80">get_weather</span>
                <span className="text-muted-foreground/30">·</span>
                <span className="text-muted-foreground/60">Tokyo</span>
                <div className="ml-auto">
                  {step === 1 ? <Loader2 className="h-3 w-3 animate-spin text-blue-400" /> : <CheckCircle className="h-3 w-3 text-emerald-400" />}
                </div>
              </div>
            </motion.div>
          )}
          {step >= 2 && (
            <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
              <div className="flex items-center gap-2 rounded-lg border border-border/25 bg-muted/20 px-3 py-1.5 text-[10px]">
                <Wrench className="h-3 w-3 text-muted-foreground/60" />
                <span className="font-mono text-muted-foreground/80">web_search</span>
                <span className="text-muted-foreground/30">·</span>
                <span className="text-muted-foreground/60">AI news today</span>
                <div className="ml-auto">
                  {step === 2 ? <Loader2 className="h-3 w-3 animate-spin text-blue-400" /> : <CheckCircle className="h-3 w-3 text-emerald-400" />}
                </div>
              </div>
            </motion.div>
          )}
          {step >= 3 && (
            <motion.div className="flex justify-start" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}>
              <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-border/25 bg-muted/20 px-3.5 py-2 text-[11px] leading-relaxed text-foreground/90">
                Tokyo is <span className="font-medium text-foreground">18°C, partly cloudy</span>. Today in AI: Anthropic expanded Claude&apos;s context window, OpenAI shipped GPT-5, and multi-agent orchestration is the dominant enterprise trend.
              </div>
            </motion.div>
          )}
        </div>
      </div>
      <div className="border-t border-border/15 px-3 py-2">
        <div className="flex items-center gap-2 rounded-lg border border-border/20 bg-muted/10 px-3 py-1.5">
          <span className="flex-1 text-[11px] text-muted-foreground/30 italic">Ask your agent…</span>
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-primary/60">
            <ArrowRight className="h-2.5 w-2.5 text-primary-foreground" />
          </div>
        </div>
      </div>
    </div>
  )
}

function AgentsDemo() {
  const agents = [
    { name: "Research Agent", model: "claude-sonnet-4-6", tools: ["web_search", "get_weather"], kb: ["Company docs"], active: true },
    { name: "Code Assistant",  model: "gpt-4o",            tools: ["calculator", "http_request"],  kb: [],             active: true },
    { name: "Data Analyst",    model: "gemini-2.5-flash",  tools: ["calculator"],                  kb: ["Sales data"], active: false },
  ]
  return (
    <div className="flex h-full flex-col gap-2 p-3 overflow-auto">
      {agents.map((a, i) => (
        <motion.div key={a.name} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.1 }}
          className="rounded-xl border border-border/25 bg-muted/10 p-3">
          <div className="flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 mt-0.5">
              <Bot className="h-3.5 w-3.5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[11px] font-semibold">{a.name}</span>
                <span className={`h-1.5 w-1.5 rounded-full ${a.active ? "bg-emerald-400" : "bg-muted-foreground/25"}`} />
                <span className="ml-auto font-mono text-[10px] text-muted-foreground/60">{a.model}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {a.tools.map((t) => (
                  <span key={t} className="flex items-center gap-0.5 rounded-md border border-border/30 bg-background/40 px-1.5 py-0.5 text-[9px] font-mono text-muted-foreground/70">
                    <Wrench className="h-2 w-2" />{t}
                  </span>
                ))}
                {a.kb.map((k) => (
                  <span key={k} className="flex items-center gap-0.5 rounded-md border border-border/20 bg-muted/20 px-1.5 py-0.5 text-[9px] font-mono text-muted-foreground/60">
                    <BookOpen className="h-2 w-2" />{k}
                  </span>
                ))}
              </div>
            </div>
            <Settings className="h-3.5 w-3.5 shrink-0 text-muted-foreground/25 mt-0.5" />
          </div>
        </motion.div>
      ))}
    </div>
  )
}

function TeamsDemo() {
  const [active, setActive] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setActive((a) => (a + 1) % 3), 2000)
    return () => clearInterval(t)
  }, [])

  const agents = [
    { name: "Coordinator",    role: "Routes queries to specialists",   status: "routing",    col: "chart-1" },
    { name: "Research Agent", role: "Fetches & synthesises sources",   status: "responding", col: "chart-2" },
    { name: "Summarizer",     role: "Produces final concise output",   status: "waiting",    col: "chart-5" },
  ]

  return (
    <div className="flex h-full flex-col gap-2.5 p-3">
      <div className="rounded-xl border border-border/25 bg-muted/10 p-3">
        <div className="flex items-center gap-2 mb-3">
          <Users className="h-3.5 w-3.5 text-muted-foreground/60" />
          <span className="text-[11px] font-semibold">Research Team</span>
          <span className="ml-auto flex items-center gap-1 text-[10px] text-emerald-400 font-medium">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />running
          </span>
        </div>
        <div className="flex flex-col gap-1.5">
          {agents.map((ag, i) => (
            <div key={ag.name} className={`flex items-center gap-2.5 rounded-lg px-2.5 py-2 transition-all duration-300 ${active === i ? "bg-muted/30 border border-border/25" : "bg-transparent"}`}>
              <div className={`h-6 w-6 shrink-0 flex items-center justify-center rounded-full bg-${ag.col}/10`}>
                <Bot className={`h-3 w-3 text-${ag.col}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-medium">{ag.name}</div>
                <div className="text-[9px] text-muted-foreground/60">{ag.role}</div>
              </div>
              <span className={`text-[10px] font-mono ${active === i ? `text-${ag.col}` : "text-muted-foreground/30"}`}>
                {active === i ? ag.status : "idle"}
              </span>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-lg border border-border/20 bg-muted/5 px-3 py-2 text-[11px] text-muted-foreground/70 leading-relaxed">
        <span className="text-foreground/70 font-medium">Coordinator</span> delegated to <span className="text-foreground/70 font-medium">Research Agent</span> — fetching and synthesising sources in real time…
      </div>
    </div>
  )
}

function DAGDemo() {
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    setPhase(0)
    const t1 = setTimeout(() => setPhase(1), 1000)
    const t2 = setTimeout(() => setPhase(2), 2400)
    const t3 = setTimeout(() => setPhase(3), 3600)
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3) }
  }, [])

  const getStatus = (id: number) => {
    if (id === 0) return phase >= 2 ? "done" : phase === 1 ? "running" : "idle"
    if (id === 1 || id === 2) return phase >= 3 ? "done" : phase === 2 ? "running" : "idle"
    if (id === 3) return phase >= 3 ? "running" : "idle"
    return "idle"
  }

  return (
    <div className="flex h-full flex-col p-3 gap-2">
      <div className="flex items-center gap-2 mb-0.5">
        <GitBranch className="h-3.5 w-3.5 text-muted-foreground/60" />
        <span className="text-[11px] font-semibold">Report Pipeline — DAG</span>
        <span className="ml-auto flex items-center gap-1 text-[10px] text-blue-400 font-medium">
          <Loader2 className="h-2.5 w-2.5 animate-spin" />executing
        </span>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center gap-1.5">
        <DagNode label="Fetch Data" sub="HTTP tool" status={getStatus(0)} />

        <div className="flex items-center gap-1 text-muted-foreground/30 text-[9px] font-mono">
          <div className="h-4 w-px bg-border/30" />
          <span>parallel fan-out</span>
          <div className="h-4 w-px bg-border/30" />
        </div>

        <div className="flex gap-2 w-full max-w-xs justify-center">
          <DagNode label="Summarize" sub="claude-sonnet-4-6" status={getStatus(1)} compact />
          <DagNode label="Classify"  sub="gpt-4o-mini"       status={getStatus(2)} compact />
        </div>

        <div className="flex items-center gap-1 text-muted-foreground/30 text-[9px] font-mono">
          <div className="h-4 w-px bg-border/30" />
          <span>join</span>
          <div className="h-4 w-px bg-border/30" />
        </div>

        <DagNode label="Send Report" sub="Slack webhook" status={getStatus(3)} />
      </div>
    </div>
  )
}

function DagNode({ label, sub, status, compact }: { label: string; sub: string; status: string; compact?: boolean }) {
  const isRunning = status === "running"
  const isDone = status === "done"
  return (
    <motion.div
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition-colors ${compact ? "w-[46%]" : "w-3/5"} ${
        isDone ? "border-emerald-500/30 bg-emerald-500/5" :
        isRunning ? "border-blue-500/30 bg-blue-500/5" :
        "border-border/20 bg-muted/10"
      }`}
      animate={isRunning ? { boxShadow: ["0 0 0px rgba(59,130,246,0)", "0 0 8px rgba(59,130,246,0.2)", "0 0 0px rgba(59,130,246,0)"] } : {}}
      transition={{ duration: 1.2, repeat: Infinity }}
    >
      <div className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${isDone ? "bg-emerald-500/10" : isRunning ? "bg-blue-500/10" : "bg-muted/30"}`}>
        {isDone    ? <CheckCircle className="h-3 w-3 text-emerald-400" /> :
         isRunning ? <Loader2 className="h-3 w-3 animate-spin text-blue-400" /> :
                    <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/20" />}
      </div>
      <div className="min-w-0">
        <div className={`text-[11px] font-medium truncate ${isDone ? "text-foreground/80" : isRunning ? "text-blue-400" : "text-muted-foreground/40"}`}>{label}</div>
        <div className="text-[9px] font-mono text-muted-foreground/40 truncate">{sub}</div>
      </div>
    </motion.div>
  )
}

function WorkflowDemo() {
  const [progress, setProgress] = useState(1)
  useEffect(() => {
    const t = setInterval(() => setProgress((p) => (p < 3 ? p + 1 : 1)), 1800)
    return () => clearInterval(t)
  }, [])

  const steps = [
    { label: "HTTP Trigger",   sub: "POST /webhook/daily-report",          icon: Workflow },
    { label: "Research Agent", sub: "Searches web, reads KB",              icon: Bot },
    { label: "Summarize",      sub: "claude-sonnet-4-6 · structured output", icon: Cpu },
    { label: "Send Report",    sub: "POST to Slack webhook",               icon: ArrowRight },
  ]

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <div className="flex items-center gap-2 mb-1">
        <Workflow className="h-3.5 w-3.5 text-muted-foreground/60" />
        <span className="text-[11px] font-semibold">Daily Report Pipeline</span>
        <span className="ml-auto flex items-center gap-1 text-[10px] text-blue-400 font-medium">
          <Loader2 className="h-2.5 w-2.5 animate-spin" />running
        </span>
      </div>
      {steps.map((step, i) => {
        const done = i < progress, running = i === progress
        const Icon = step.icon
        return (
          <motion.div key={step.label} className="flex items-start gap-3" initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.07 }}>
            <div className="flex flex-col items-center">
              <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${done ? "border-emerald-500/30 bg-emerald-500/10" : running ? "border-blue-500/30 bg-blue-500/10" : "border-border/20 bg-muted/10"}`}>
                {done ? <CheckCircle className="h-3 w-3 text-emerald-400" /> :
                 running ? <motion.div animate={{ rotate: 360 }} transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}><Loader2 className="h-3 w-3 text-blue-400" /></motion.div> :
                 <Icon className="h-2.5 w-2.5 text-muted-foreground/25" />}
              </div>
              {i < steps.length - 1 && <div className={`w-px mt-1 ${done ? "bg-emerald-500/20" : "bg-border/15"}`} style={{ minHeight: 12 }} />}
            </div>
            <div className="pt-0.5 pb-2">
              <div className={`text-[11px] font-medium ${running ? "text-blue-400" : done ? "text-foreground/80" : "text-muted-foreground/40"}`}>{step.label}</div>
              <div className="text-[10px] text-muted-foreground/50 font-mono">{step.sub}</div>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Config                                                              */
/* ------------------------------------------------------------------ */
const DEMOS = [
  { id: "playground", label: "Playground", icon: MessageSquare, Demo: PlaygroundDemo, desc: "Real-time streaming chat with live tool call visualization" },
  { id: "agents",     label: "Agents",     icon: Bot,           Demo: AgentsDemo,     desc: "Configure agents with any LLM, tools, and knowledge bases" },
  { id: "teams",      label: "Teams",      icon: Users,         Demo: TeamsDemo,      desc: "Multi-agent teams that route, coordinate, and collaborate" },
  { id: "dag",        label: "DAG",        icon: GitBranch,     Demo: DAGDemo,        desc: "Visual parallel pipeline editor with live node visualization" },
  { id: "workflows",  label: "Workflows",  icon: Workflow,      Demo: WorkflowDemo,   desc: "Scheduled and triggered pipelines with per-step streaming" },
]

const CHIPS = [
  { icon: Bot,        label: "Agent builder" },
  { icon: Users,      label: "Multi-agent teams" },
  { icon: GitBranch,  label: "Visual DAG" },
  { icon: Workflow,   label: "Scheduled workflows" },
  { icon: Brain,      label: "Long-term memory" },
  { icon: BookOpen,   label: "Knowledge bases" },
  { icon: FileCode2,  label: "Artifacts" },
  { icon: Wrench,     label: "Tools & MCP" },
  { icon: Shield,     label: "HITL approvals" },
  { icon: Server,     label: "MCP protocol" },
  { icon: Key,        label: "Secrets vault" },
  { icon: Database,   label: "Exec traces" },
  { icon: Cpu,        label: "2FA & RBAC" },
  { icon: Settings,   label: "Admin panel" },
  { icon: MessageSquare, label: "File attachments" },
  { icon: Sparkles,   label: "Multi-provider LLMs" },
]

const CHIP_DELAYS = [0.38, 0.44, 0.50, 0.42, 0.56, 0.48, 0.52, 0.46, 0.60, 0.54, 0.58, 0.40, 0.64, 0.62, 0.53, 0.67]

/* ------------------------------------------------------------------ */
/*  Hero                                                                */
/* ------------------------------------------------------------------ */
export function Hero() {
  const router = useRouter()
  const [activeIdx, setActiveIdx] = useState(0)
  const [resetKey, setResetKey] = useState(0)

  useEffect(() => {
    const t = setInterval(() => {
      setActiveIdx((d) => (d + 1) % DEMOS.length)
      setResetKey((k) => k + 1)
    }, 6000)
    return () => clearInterval(t)
  }, [])

  const handleTab = (i: number) => { setActiveIdx(i); setResetKey((k) => k + 1) }
  const { Demo, desc } = DEMOS[activeIdx]

  return (
    <section className="relative overflow-hidden pb-20">
      <Background />

      <div className="relative z-10 mx-auto max-w-screen-2xl px-8 pt-16 sm:pt-24">

        {/* ── Two-column top row: headline left, chip cloud right ── */}
        <div className="mb-10 flex items-stretch gap-8">

          {/* Left: headline block */}
          <motion.div
            className="min-w-0 w-full lg:w-[48%] xl:w-[44%] shrink-0 flex flex-col justify-between"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            {/* Eyebrow badge */}
            <motion.div
              className="mb-6 inline-flex items-center gap-2 rounded-full border border-border/40 bg-muted/20 px-4 py-1.5 backdrop-blur-sm"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: 0.1 }}
            >
              <Sparkles className="h-3 w-3 text-muted-foreground/60" />
              <span className="text-[11px] font-medium tracking-wide text-muted-foreground/80">Open-source · AGPL-3.0</span>
              <span className="h-3 w-px bg-border/50" />
              <a
                href="https://github.com/sup3rus3r/obsidian-ai"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-[11px] text-muted-foreground/60 hover:text-foreground transition-colors"
              >
                <Github className="h-3 w-3" />Star on GitHub
              </a>
            </motion.div>

            {/* Headline */}
            <motion.h1
              className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl leading-[1.08] mb-5"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
            >
              The orchestration layer{" "}
              <span className="text-muted-foreground/45">
                for production AI agents.
              </span>
            </motion.h1>

            {/* Sub */}
            <motion.p
              className="max-w-md text-base sm:text-lg text-muted-foreground leading-relaxed mb-8"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.22 }}
            >
              Connect any LLM, compose multi-agent teams, design parallel pipelines,
              and stream every execution — self-hosted, open-source, no vendor lock-in.
            </motion.p>

            {/* CTAs */}
            <motion.div
              className="flex items-center gap-3"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.28 }}
            >
              <Button size="lg" className="cursor-pointer gap-2 flex-1 text-sm font-semibold" onClick={() => router.push("/register")}>
                Get Started <ArrowRight className="h-4 w-4" />
              </Button>
              <Button size="lg" variant="outline" className="cursor-pointer flex-1 text-sm" onClick={() => router.push("/login")}>
                Sign In
              </Button>
            </motion.div>
          </motion.div>

          {/* Right: bento grid */}
          <div className="hidden lg:block flex-1 self-stretch relative rounded-2xl overflow-hidden" style={{ border: "1px solid rgba(74,222,128,0.30)", boxShadow: "0 0 20px rgba(74,222,128,0.07), 0 0 60px rgba(74,222,128,0.04), inset 0 0 30px rgba(74,222,128,0.02)" }}>
            {/* Fading grid background */}
            <div
              className="absolute inset-0"
              style={{
                backgroundImage: `linear-gradient(to right, hsl(var(--foreground)/0.06) 1px, transparent 1px),
                                  linear-gradient(to bottom, hsl(var(--foreground)/0.06) 1px, transparent 1px)`,
                backgroundSize: "64px 64px",
                WebkitMaskImage: "radial-gradient(ellipse 90% 90% at 50% 50%, black 30%, transparent 100%)",
                maskImage: "radial-gradient(ellipse 90% 90% at 50% 50%, black 30%, transparent 100%)",
              }}
            />
            {/* Bento cells */}
            <div className="relative z-10 grid grid-cols-3 grid-rows-3 gap-2.5 h-full min-h-80 p-1">

              {/* [0,0] span-2 wide — Agents & Teams */}
              <motion.div
                className="col-span-2 row-span-1 rounded-xl border border-border/25 bg-card/20 backdrop-blur-sm p-4 flex flex-col justify-between"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.38 }}
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-muted/30 border border-border/20">
                    <Users className="h-3.5 w-3.5 text-foreground/60" />
                  </div>
                  <span className="text-[13px] font-semibold text-foreground/80">Agent orchestration</span>
                </div>
                <p className="text-[11px] text-muted-foreground/60 leading-relaxed">
                  Solo agents, coordinated teams, or visual DAG pipelines — pick the pattern that fits.
                </p>
              </motion.div>

              {/* [0,2] tall — Memory */}
              <motion.div
                className="col-span-1 row-span-2 rounded-xl border border-border/25 bg-card/20 backdrop-blur-sm p-4 flex flex-col gap-3"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.44 }}
              >
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted/30 border border-border/20">
                  <Brain className="h-4 w-4 text-foreground/60" />
                </div>
                <div>
                  <div className="text-[13px] font-semibold text-foreground/80 mb-1">Long-term memory</div>
                  <p className="text-[11px] text-muted-foreground/60 leading-relaxed">
                    Agents learn and remember across sessions. Model-extracted, editable, bounded.
                  </p>
                </div>
                <div className="mt-auto flex flex-col gap-1.5">
                  {["Preference", "Context", "Decision", "Correction"].map((c) => (
                    <div key={c} className="flex items-center gap-1.5 text-[10px] text-muted-foreground/50">
                      <div className="h-1 w-1 rounded-full bg-foreground/20" />{c}
                    </div>
                  ))}
                </div>
              </motion.div>

              {/* [1,0] — Knowledge */}
              <motion.div
                className="col-span-1 row-span-1 rounded-xl border border-border/25 bg-card/20 backdrop-blur-sm p-4 flex flex-col justify-between"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.48 }}
              >
                <BookOpen className="h-4 w-4 text-foreground/50 mb-2" />
                <div>
                  <div className="text-[12px] font-semibold text-foreground/80">Knowledge bases</div>
                  <div className="text-[10px] text-muted-foreground/55 mt-0.5">RAG-powered, per-agent</div>
                </div>
              </motion.div>

              {/* [1,1] — Tools */}
              <motion.div
                className="col-span-1 row-span-1 rounded-xl border border-border/25 bg-card/20 backdrop-blur-sm p-4 flex flex-col justify-between"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.52 }}
              >
                <Wrench className="h-4 w-4 text-foreground/50 mb-2" />
                <div>
                  <div className="text-[12px] font-semibold text-foreground/80">Tools & MCP</div>
                  <div className="text-[10px] text-muted-foreground/55 mt-0.5">Custom Python · REST · stdio</div>
                </div>
              </motion.div>

              {/* [2,0] span-2 — Security */}
              <motion.div
                className="col-span-2 row-span-1 rounded-xl border border-border/25 bg-card/20 backdrop-blur-sm p-4 flex items-center gap-4"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.56 }}
              >
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted/30 border border-border/20">
                  <Shield className="h-4 w-4 text-foreground/60" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-semibold text-foreground/80 mb-1">Security-first</div>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                    {["2FA · TOTP", "AES encryption", "Fernet at rest", "JWT auth", "RBAC"].map((t) => (
                      <span key={t} className="text-[10px] text-muted-foreground/50">{t}</span>
                    ))}
                  </div>
                </div>
              </motion.div>

              {/* [2,2] — Artifacts */}
              <motion.div
                className="col-span-1 row-span-1 rounded-xl border border-border/25 bg-card/20 backdrop-blur-sm p-4 flex flex-col justify-between"
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.60 }}
              >
                <FileCode2 className="h-4 w-4 text-foreground/50 mb-2" />
                <div>
                  <div className="text-[12px] font-semibold text-foreground/80">Artifacts</div>
                  <div className="text-[10px] text-muted-foreground/55 mt-0.5">HTML · JSX · SVG · live</div>
                </div>
              </motion.div>

            </div>
          </div>
        </div>

        {/* ── Demo window ── */}
        <div className="relative">
          {/* Demo window */}
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.35 }}
            className="rounded-2xl border border-border/30 bg-card/30 backdrop-blur-2xl shadow-2xl overflow-hidden ring-1 ring-white/5"
          >
            {/* Window chrome */}
            <div className="flex items-center gap-2 border-b border-border/20 bg-muted/10 px-4 py-2.5">
              <div className="flex gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-red-500/40" />
                <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/40" />
                <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/40" />
              </div>
              <span className="ml-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/40">
                Obsidian AI
              </span>
              <div className="ml-auto flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-[10px] text-muted-foreground/40">live</span>
              </div>
            </div>

            {/* Tab bar */}
            <div className="flex border-b border-border/15 bg-muted/5 overflow-x-auto scrollbar-none">
              {DEMOS.map(({ id, label, icon: Icon }, i) => (
                <button
                  key={id}
                  onClick={() => handleTab(i)}
                  className={`flex shrink-0 items-center gap-1.5 px-4 py-2.5 text-[11px] font-medium border-b-2 transition-all ${
                    activeIdx === i
                      ? "border-primary text-foreground bg-background/20"
                      : "border-transparent text-muted-foreground/60 hover:text-muted-foreground hover:bg-background/10"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="hidden sm:inline">{label}</span>
                </button>
              ))}
              <div className="hidden md:flex flex-1 items-center justify-end px-4">
                <AnimatePresence mode="wait">
                  <motion.span
                    key={activeIdx}
                    className="text-[10px] text-muted-foreground/40 italic"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.18 }}
                  >
                    {desc}
                  </motion.span>
                </AnimatePresence>
              </div>
            </div>

            {/* Content */}
            <div className="h-80 sm:h-90 overflow-hidden">
              <AnimatePresence mode="wait">
                <motion.div
                  key={`${activeIdx}-${resetKey}`}
                  className="h-full"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.2 }}
                >
                  <Demo />
                </motion.div>
              </AnimatePresence>
            </div>

            {/* Progress bar */}
            <div className="h-px bg-border/10">
              <motion.div
                key={`bar-${activeIdx}-${resetKey}`}
                className="h-full bg-foreground/20"
                initial={{ width: "0%" }}
                animate={{ width: "100%" }}
                transition={{ duration: 6, ease: "linear" }}
              />
            </div>
          </motion.div>
        </div>

      </div>
    </section>
  )
}
