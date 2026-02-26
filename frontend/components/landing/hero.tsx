"use client"

import { motion, AnimatePresence } from "motion/react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  ArrowRight,
  Sparkles,
  Bot,
  Workflow,
  Zap,
  Shield,
  MessageSquare,
  CheckCircle,
  Wrench,
  Users,
  Settings,
  Database,
  Key,
  Cpu,
  Play,
  Loader2,
  BookOpen,
} from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"

/* ------------------------------------------------------------------ */
/*  Canvas background                                                   */
/* ------------------------------------------------------------------ */
function NetworkCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let animationId: number
    let width = 0, height = 0
    const nodes: { x: number; y: number; vx: number; vy: number; r: number; pulse: number; speed: number }[] = []

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const init = () => {
      resize()
      nodes.length = 0
      for (let i = 0; i < 50; i++) {
        nodes.push({
          x: Math.random() * width, y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
          r: Math.random() * 1.5 + 0.5, pulse: Math.random() * Math.PI * 2,
          speed: Math.random() * 0.015 + 0.008,
        })
      }
    }

    const draw = () => {
      ctx.clearRect(0, 0, width, height)
      for (const n of nodes) {
        n.x += n.vx; n.y += n.vy; n.pulse += n.speed
        if (n.x < 0 || n.x > width) n.vx *= -1
        if (n.y < 0 || n.y > height) n.vy *= -1
      }
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < 160) {
            ctx.beginPath()
            ctx.moveTo(nodes[i].x, nodes[i].y)
            ctx.lineTo(nodes[j].x, nodes[j].y)
            ctx.strokeStyle = `rgba(148,163,184,${(1 - dist / 160) * 0.08})`
            ctx.lineWidth = 0.5
            ctx.stroke()
          }
        }
      }
      for (const n of nodes) {
        const g = Math.sin(n.pulse) * 0.3 + 0.7
        ctx.beginPath()
        ctx.arc(n.x, n.y, n.r * g, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(148,163,184,${0.2 * g})`
        ctx.fill()
      }
      animationId = requestAnimationFrame(draw)
    }

    init(); draw()
    window.addEventListener("resize", init)
    return () => { cancelAnimationFrame(animationId); window.removeEventListener("resize", init) }
  }, [])

  return <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden />
}

/* ------------------------------------------------------------------ */
/*  Demo tab content                                                    */
/* ------------------------------------------------------------------ */
function PlaygroundDemo() {
  const [step, setStep] = useState(0)

  // Animate through steps on mount
  useEffect(() => {
    const timers = [
      setTimeout(() => setStep(1), 600),
      setTimeout(() => setStep(2), 1400),
      setTimeout(() => setStep(3), 2400),
    ]
    return () => timers.forEach(clearTimeout)
  }, [])

  return (
    <div className="flex h-full flex-col">
      {/* Sidebar */}
      <div className="flex flex-1 overflow-hidden">
        <div className="hidden sm:flex w-44 shrink-0 flex-col border-r border-border/20 bg-muted/10 p-2 gap-0.5">
          <div className="px-2 py-1 text-[9px] font-medium uppercase tracking-widest text-muted-foreground/50 mb-1">Sessions</div>
          {["Research session", "Code review", "Data analysis"].map((s, i) => (
            <div key={s} className={`flex items-center gap-2 rounded px-2 py-1.5 text-[11px] cursor-default ${i === 0 ? "bg-background/60 text-foreground border border-border/30" : "text-muted-foreground"}`}>
              <MessageSquare className="h-3 w-3 shrink-0" />
              <span className="truncate">{s}</span>
            </div>
          ))}
        </div>

        {/* Chat area */}
        <div className="flex flex-1 flex-col gap-2.5 overflow-hidden p-3">
          {/* User message */}
          <motion.div
            className="flex justify-end"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-3.5 py-2 text-xs text-primary-foreground">
              What&apos;s the weather in Tokyo and summarise recent AI news?
            </div>
          </motion.div>

          {/* Tool call */}
          {step >= 1 && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
              <div className="flex items-center gap-1.5 rounded-lg border border-border/30 bg-muted/40 px-3 py-2 text-[10px]">
                <Wrench className="h-3 w-3 text-muted-foreground" />
                <span className="font-mono text-muted-foreground">get_weather</span>
                <span className="text-muted-foreground/50">·</span>
                <span className="text-muted-foreground/70">location: Tokyo</span>
                <div className="ml-auto flex items-center gap-1">
                  {step === 1 ? (
                    <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
                  ) : (
                    <CheckCircle className="h-3 w-3 text-emerald-500" />
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {step >= 2 && (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
              <div className="flex items-center gap-1.5 rounded-lg border border-border/30 bg-muted/40 px-3 py-2 text-[10px]">
                <Wrench className="h-3 w-3 text-muted-foreground" />
                <span className="font-mono text-muted-foreground">web_search</span>
                <span className="text-muted-foreground/50">·</span>
                <span className="text-muted-foreground/70">query: recent AI news</span>
                <div className="ml-auto">
                  {step === 2 ? (
                    <Loader2 className="h-3 w-3 animate-spin text-blue-500" />
                  ) : (
                    <CheckCircle className="h-3 w-3 text-emerald-500" />
                  )}
                </div>
              </div>
            </motion.div>
          )}

          {/* Assistant response */}
          {step >= 3 && (
            <motion.div className="flex justify-start" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
              <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-border/30 bg-muted/40 px-3.5 py-2 text-xs leading-relaxed">
                Tokyo is currently <span className="font-medium">18°C and partly cloudy</span>. In AI news: OpenAI released GPT-5, Anthropic expanded Claude&apos;s context window, and multi-agent frameworks are seeing rapid adoption across enterprises.
              </div>
            </motion.div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-border/20 px-3 py-2">
        <div className="flex items-center gap-2 rounded-lg border border-border/30 bg-background/50 px-3 py-1.5">
          <span className="flex-1 text-[11px] text-muted-foreground/40 italic">Ask your agent…</span>
          <div className="flex h-5 w-5 items-center justify-center rounded-md bg-primary/70">
            <ArrowRight className="h-2.5 w-2.5 text-primary-foreground" />
          </div>
        </div>
      </div>
    </div>
  )
}

function AgentsDemo() {
  const agents = [
    {
      name: "Research Agent",
      model: "claude-sonnet-4-6",
      prompt: "You are a research assistant. Search the web and synthesise findings clearly.",
      tools: ["web_search", "get_weather"],
      kb: ["Company docs"],
      active: true,
    },
    {
      name: "Code Assistant",
      model: "gpt-4o",
      prompt: "You are an expert software engineer. Write clean, well-tested code.",
      tools: ["calculator", "http_request"],
      kb: [],
      active: true,
    },
    {
      name: "Data Analyst",
      model: "gemini-2.0-flash",
      prompt: "Analyse data and produce clear visualisations and insights.",
      tools: ["calculator"],
      kb: ["Sales data"],
      active: false,
    },
  ]

  return (
    <div className="flex h-full flex-col gap-2 p-3 overflow-auto">
      {agents.map((a, i) => (
        <motion.div
          key={a.name}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3, delay: i * 0.1 }}
          className="rounded-lg border border-border/30 bg-muted/20 p-3"
        >
          <div className="flex items-start gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 mt-0.5">
              <Bot className="h-4 w-4 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-xs font-semibold">{a.name}</span>
                <span className={`h-1.5 w-1.5 rounded-full ${a.active ? "bg-emerald-500" : "bg-muted-foreground/30"}`} />
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">{a.model}</span>
              </div>
              <p className="text-[10px] text-muted-foreground leading-relaxed line-clamp-1 mb-2">{a.prompt}</p>
              <div className="flex flex-wrap gap-1">
                {a.tools.map((t) => (
                  <span key={t} className="flex items-center gap-0.5 rounded border border-border/40 bg-background/60 px-1.5 py-0.5 text-[9px] font-mono text-muted-foreground">
                    <Wrench className="h-2 w-2" />{t}
                  </span>
                ))}
                {a.kb.map((k) => (
                  <span key={k} className="flex items-center gap-0.5 rounded border border-chart-1/20 bg-chart-1/5 px-1.5 py-0.5 text-[9px] font-mono text-chart-1">
                    <BookOpen className="h-2 w-2" />{k}
                  </span>
                ))}
              </div>
            </div>
            <Settings className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40 mt-1 cursor-pointer hover:text-muted-foreground transition-colors" />
          </div>
        </motion.div>
      ))}
    </div>
  )
}

function TeamsDemo() {
  const [activeAgent, setActiveAgent] = useState(1)

  useEffect(() => {
    const t = setInterval(() => setActiveAgent((a) => (a + 1) % 3), 2000)
    return () => clearInterval(t)
  }, [])

  const agents = [
    { name: "Coordinator", role: "Routes queries to specialists", status: "routing", color: "chart-1" },
    { name: "Research Agent", role: "Fetches & summarises information", status: "responding", color: "chart-2" },
    { name: "Summarizer", role: "Produces final concise output", status: "waiting", color: "chart-5" },
  ]

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <div className="rounded-lg border border-border/30 bg-muted/20 p-3">
        <div className="flex items-center gap-2 mb-3">
          <Users className="h-3.5 w-3.5 text-chart-1" />
          <span className="text-xs font-semibold">Research Team</span>
          <span className="ml-auto flex items-center gap-1 text-[10px] text-emerald-500 font-medium">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            running
          </span>
        </div>
        <div className="flex flex-col gap-1.5">
          {agents.map((agent, i) => (
            <motion.div
              key={agent.name}
              className={`flex items-center gap-2.5 rounded-md px-2.5 py-2 transition-colors ${
                activeAgent === i ? "bg-background/70 border border-border/30" : "bg-background/20"
              }`}
            >
              <div className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-${agent.color}/10`}>
                <Bot className={`h-3 w-3 text-${agent.color}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] font-medium truncate">{agent.name}</div>
                <div className="text-[9px] text-muted-foreground truncate">{agent.role}</div>
              </div>
              <div className={`text-[10px] font-mono ${activeAgent === i ? `text-${agent.color}` : "text-muted-foreground/40"}`}>
                {activeAgent === i ? agent.status : "idle"}
              </div>
              {activeAgent === i && agent.status === "responding" && (
                <motion.div
                  className="flex gap-0.5"
                  animate={{ opacity: [1, 0.4, 1] }}
                  transition={{ duration: 0.8, repeat: Infinity }}
                >
                  {[0, 1, 2].map((d) => (
                    <span key={d} className={`h-1 w-1 rounded-full bg-${agent.color}`} style={{ animationDelay: `${d * 0.15}s` }} />
                  ))}
                </motion.div>
              )}
            </motion.div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-border/20 bg-background/20 px-3 py-2 text-[11px] text-muted-foreground leading-relaxed">
        <span className="text-chart-1 font-medium">Coordinator</span> routed the query to <span className="text-chart-2 font-medium">Research Agent</span> — currently searching for relevant sources…
      </div>
    </div>
  )
}

function WorkflowDemo() {
  const [progress, setProgress] = useState(1)

  useEffect(() => {
    const t = setInterval(() => setProgress((p) => (p < 3 ? p + 1 : 1)), 1800)
    return () => clearInterval(t)
  }, [])

  const steps = [
    { label: "HTTP Trigger", sub: "POST /webhook/daily-report", icon: Zap },
    { label: "Research Agent", sub: "Searches web, reads KB", icon: Bot },
    { label: "Summarize", sub: "claude-sonnet-4-6 · structured output", icon: Cpu },
    { label: "Send Report", sub: "POST to Slack webhook", icon: ArrowRight },
  ]

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <div className="flex items-center gap-2 mb-1">
        <Workflow className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold">Daily Report Pipeline</span>
        <span className="ml-auto flex items-center gap-1 text-[10px] text-blue-500 font-medium">
          <Loader2 className="h-2.5 w-2.5 animate-spin" />
          running
        </span>
      </div>

      {steps.map((step, i) => {
        const done = i < progress
        const running = i === progress
        const Icon = step.icon
        return (
          <motion.div
            key={step.label}
            className="flex items-start gap-3"
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3, delay: i * 0.08 }}
          >
            <div className="flex flex-col items-center">
              <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition-colors ${
                done ? "border-emerald-500/40 bg-emerald-500/10" :
                running ? "border-blue-500/40 bg-blue-500/10" :
                "border-border/30 bg-muted/20"
              }`}>
                {done ? (
                  <CheckCircle className="h-3.5 w-3.5 text-emerald-500" />
                ) : running ? (
                  <motion.div animate={{ rotate: 360 }} transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}>
                    <Loader2 className="h-3.5 w-3.5 text-blue-500" />
                  </motion.div>
                ) : (
                  <Icon className="h-3 w-3 text-muted-foreground/40" />
                )}
              </div>
              {i < steps.length - 1 && (
                <div className={`w-px my-1 transition-colors ${done ? "bg-emerald-500/30" : "bg-border/20"}`} style={{ minHeight: 14 }} />
              )}
            </div>
            <div className="pt-1 pb-2">
              <div className={`text-xs font-medium leading-none ${running ? "text-blue-500" : done ? "text-foreground" : "text-muted-foreground/50"}`}>
                {step.label}
              </div>
              <div className="text-[10px] text-muted-foreground/60 mt-0.5 font-mono">{step.sub}</div>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Feature pills shown below the demo                                  */
/* ------------------------------------------------------------------ */
const FEATURES = [
  { icon: Bot,       label: "Agent builder",        sub: "Any LLM, tools, system prompt" },
  { icon: Users,     label: "Multi-agent teams",    sub: "Route, coordinate, collaborate" },
  { icon: Workflow,  label: "Workflow automation",  sub: "Scheduled & triggered pipelines" },
  { icon: Wrench,    label: "Tool execution",       sub: "Python, HTTP & MCP servers" },
  { icon: BookOpen,  label: "Knowledge bases",      sub: "RAG over your documents" },
  { icon: Database,  label: "Session history",      sub: "Full message replay" },
  { icon: Key,       label: "Secrets vault",        sub: "Encrypted API key storage" },
  { icon: Shield,    label: "2FA & RBAC",           sub: "Enterprise-grade auth" },
]

/* ------------------------------------------------------------------ */
/*  Demo tabs config                                                    */
/* ------------------------------------------------------------------ */
const DEMOS = [
  { id: "playground", label: "Playground", icon: MessageSquare, description: "Chat with any agent in real time, watch tool calls happen live" },
  { id: "agents",     label: "Agents",     icon: Bot,           description: "Configure agents with models, tools, prompts & knowledge bases" },
  { id: "teams",      label: "Teams",      icon: Users,         description: "Coordinate fleets of agents that work together" },
  { id: "workflows",  label: "Workflows",  icon: Workflow,      description: "Automate recurring pipelines with triggers & scheduled runs" },
]

/* ------------------------------------------------------------------ */
/*  Hero                                                                */
/* ------------------------------------------------------------------ */
export function Hero() {
  const router = useRouter()
  const [activeDemo, setActiveDemo] = useState(0)
  const [resetKey, setResetKey] = useState(0)

  useEffect(() => {
    const t = setInterval(() => {
      setActiveDemo((d) => (d + 1) % DEMOS.length)
      setResetKey((k) => k + 1)
    }, 6000)
    return () => clearInterval(t)
  }, [])

  const handleTabClick = (i: number) => {
    setActiveDemo(i)
    setResetKey((k) => k + 1)
  }

  const DemoContent = [PlaygroundDemo, AgentsDemo, TeamsDemo, WorkflowDemo][activeDemo]

  return (
    <section className="relative overflow-hidden">
      <NetworkCanvas />

      {/* Blobs */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute left-1/4 top-1/3 h-[600px] w-[600px] rounded-full bg-chart-1/5 blur-[140px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute right-1/4 bottom-1/4 h-[500px] w-[500px] rounded-full bg-chart-5/5 blur-[130px]"
          animate={{ scale: [1, 1.15, 1], opacity: [0.2, 0.5, 0.2] }}
          transition={{ duration: 11, repeat: Infinity, ease: "easeInOut", delay: 3 }}
        />
      </div>

      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_20%,var(--background)_80%)]" />

      <div className="relative z-10 mx-auto max-w-6xl px-6 pt-24 pb-20 sm:pt-32">

        {/* ── Headline ── */}
        <motion.div
          className="text-center mb-10"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55 }}
        >
          <Badge variant="outline" className="mb-5 gap-1.5 border-chart-1/30 bg-chart-1/5 px-3 py-1 text-xs font-medium text-chart-1">
            <Sparkles className="h-3 w-3" />
            AI Agent Control Plane
          </Badge>

          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl !leading-[1.1] mb-5">
            Build, run & {" "}
            <span className="relative inline-block">
              <span className="bg-gradient-to-r from-chart-1 via-chart-5 to-chart-2 bg-clip-text text-transparent">
                orchestrate
              </span>
              <motion.span
                className="absolute -bottom-1 left-0 h-[3px] w-full rounded-full bg-gradient-to-r from-chart-1 via-chart-5 to-chart-2"
                initial={{ scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ duration: 0.6, delay: 0.7 }}
                style={{ transformOrigin: "left" }}
              />
            </span>
            {" "}AI agents from one place
          </h1>

          <p className="mx-auto max-w-2xl text-base sm:text-lg text-muted-foreground leading-relaxed mb-8">
            Configure agents with any LLM, attach tools and knowledge bases, wire up multi-agent teams,
            automate workflows, and chat with everything — all from a single dashboard.
          </p>

          <div className="flex items-center justify-center gap-3 flex-wrap">
            <Button size="lg" className="cursor-pointer gap-2 px-8 text-base" onClick={() => router.push("/register")}>
              Get Started <ArrowRight className="h-4 w-4" />
            </Button>
            <Button size="lg" variant="outline" className="cursor-pointer px-8 text-base" onClick={() => router.push("/login")}>
              Sign In
            </Button>
          </div>
        </motion.div>

        {/* ── Demo window ── */}
        <motion.div
          initial={{ opacity: 0, y: 32 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.25 }}
          className="rounded-2xl border border-border/40 bg-card/40 backdrop-blur-xl shadow-2xl overflow-hidden"
        >
          {/* Window chrome */}
          <div className="flex items-center gap-2 border-b border-border/30 bg-muted/20 px-4 py-2.5">
            <div className="flex gap-1.5">
              <div className="h-2.5 w-2.5 rounded-full bg-red-500/50" />
              <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/50" />
              <div className="h-2.5 w-2.5 rounded-full bg-green-500/50" />
            </div>
            <span className="ml-2 text-[10px] font-medium uppercase tracking-widest text-muted-foreground/50">
              Agent Control Plane
            </span>
            <div className="ml-auto flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-[10px] text-muted-foreground/50">live</span>
            </div>
          </div>

          {/* Tab bar */}
          <div className="flex border-b border-border/20 bg-muted/10">
            {DEMOS.map((demo, i) => {
              const Icon = demo.icon
              return (
                <button
                  key={demo.id}
                  onClick={() => handleTabClick(i)}
                  className={`flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium border-b-2 transition-all ${
                    activeDemo === i
                      ? "border-primary text-foreground bg-background/30"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:bg-background/20"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="hidden sm:inline">{demo.label}</span>
                </button>
              )
            })}
            {/* Active tab description */}
            <div className="hidden md:flex flex-1 items-center justify-end px-4 text-[11px] text-muted-foreground/60 italic">
              {DEMOS[activeDemo].description}
            </div>
          </div>

          {/* Demo content */}
          <div className="h-[320px] sm:h-[360px] overflow-hidden">
            <AnimatePresence mode="wait">
              <motion.div
                key={`${activeDemo}-${resetKey}`}
                className="h-full"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.22 }}
              >
                <DemoContent />
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Progress bar */}
          <div className="h-[2px] bg-border/10">
            <motion.div
              key={`bar-${activeDemo}-${resetKey}`}
              className="h-full bg-primary/30"
              initial={{ width: "0%" }}
              animate={{ width: "100%" }}
              transition={{ duration: 6, ease: "linear" }}
            />
          </div>
        </motion.div>

        {/* ── Feature grid ── */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.5 }}
          className="mt-12 grid grid-cols-2 sm:grid-cols-4 gap-3"
        >
          {FEATURES.map((f, i) => {
            const Icon = f.icon
            return (
              <motion.div
                key={f.label}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.6 + i * 0.04 }}
                className="flex items-start gap-2.5 rounded-xl border border-border/30 bg-card/30 backdrop-blur-sm px-3 py-2.5 hover:bg-card/50 transition-colors"
              >
                <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted/60">
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <div>
                  <div className="text-xs font-medium leading-tight">{f.label}</div>
                  <div className="text-[10px] text-muted-foreground leading-tight mt-0.5">{f.sub}</div>
                </div>
              </motion.div>
            )
          })}
        </motion.div>
      </div>
    </section>
  )
}
