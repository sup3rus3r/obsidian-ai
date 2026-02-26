"use client"

import { motion } from "motion/react"
import { Cpu, Layers, Zap, Lock, Terminal, History } from "lucide-react"

const items = [
  {
    icon: Cpu,
    title: "Multi-Provider Support",
    description:
      "Seamlessly switch between OpenAI, Anthropic, Google Gemini, Azure, and any OpenAI-compatible API. Manage provider keys and endpoints from a single settings panel.",
    className: "sm:col-span-2",
    color: "text-chart-1",
    bg: "bg-chart-1/10",
    gradient: "from-chart-1/15 via-chart-1/5 to-transparent",
    glow: "bg-chart-1/20",
    border: "hover:border-chart-1/30",
  },
  {
    icon: Layers,
    title: "MCP Servers",
    description:
      "Connect external tool servers via the Model Context Protocol. Extend agent capabilities with custom tools, databases, and third-party APIs.",
    className: "sm:col-span-1",
    color: "text-chart-2",
    bg: "bg-chart-2/10",
    gradient: "from-chart-2/15 via-chart-2/5 to-transparent",
    glow: "bg-chart-2/20",
    border: "hover:border-chart-2/30",
  },
  {
    icon: Lock,
    title: "Secrets Management",
    description:
      "Fernet-encrypted secret storage with per-user isolation. API keys and credentials are encrypted at rest and never exposed in logs or responses.",
    className: "sm:col-span-1",
    color: "text-chart-4",
    bg: "bg-chart-4/10",
    gradient: "from-chart-4/15 via-chart-4/5 to-transparent",
    glow: "bg-chart-4/20",
    border: "hover:border-chart-4/30",
  },
  {
    icon: Zap,
    title: "Streaming & Tool Execution",
    description:
      "Real-time streaming responses with live tool call visualization, reasoning traces, chain-of-thought display, and multi-step agent execution monitoring.",
    className: "sm:col-span-2",
    color: "text-chart-5",
    bg: "bg-chart-5/10",
    gradient: "from-chart-5/15 via-chart-5/5 to-transparent",
    glow: "bg-chart-5/20",
    border: "hover:border-chart-5/30",
  },
  {
    icon: Terminal,
    title: "API Client Credentials",
    description:
      "Generate client ID / secret pairs for programmatic access. Integrate Obsidian AI capabilities into your existing applications and CI/CD pipelines.",
    className: "sm:col-span-2",
    color: "text-chart-3",
    bg: "bg-chart-3/10",
    gradient: "from-chart-3/15 via-chart-3/5 to-transparent",
    glow: "bg-chart-3/20",
    border: "hover:border-chart-3/30",
  },
  {
    icon: History,
    title: "Session Replay",
    description:
      "Full conversation history with searchable sessions. Replay any past interaction, review tool calls, and audit agent behavior.",
    className: "sm:col-span-1",
    color: "text-chart-1",
    bg: "bg-chart-1/10",
    gradient: "from-chart-1/15 via-chart-1/5 to-transparent",
    glow: "bg-chart-1/20",
    border: "hover:border-chart-1/30",
  },
]

export function BentoGrid() {
  return (
    <section id="platform" className="relative py-0 sm:py-0">
      {/* Breathing background blobs */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute left-0 top-1/3 h-[500px] w-[500px] rounded-full bg-chart-2/5 blur-[160px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute right-0 bottom-1/4 h-[400px] w-[400px] rounded-full bg-chart-5/5 blur-[140px]"
          animate={{ scale: [1, 1.15, 1], opacity: [0.2, 0.5, 0.2] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut", delay: 3 }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.5 }}
          className="mx-auto max-w-2xl text-center"
        >
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Built for{" "}
            <span className="">
              production
            </span>
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Enterprise-grade infrastructure for your AI agent operations.
          </p>
        </motion.div>

        <div className="mx-auto mt-16 grid max-w-5xl gap-4 sm:grid-cols-3">
          {items.map((item, i) => (
            <motion.div
              key={item.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-50px" }}
              transition={{ duration: 0.4, delay: i * 0.08 }}
              className={`group relative overflow-hidden rounded-xl border border-border/50 bg-card/30 p-6 transition-all duration-300 hover:bg-card/50 ${item.border} ${item.className}`}
            >
              {/* Gradient overlay on hover */}
              <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${item.gradient} opacity-0 transition-opacity duration-500 group-hover:opacity-100`} />
              {/* Corner glow on hover */}
              <div className={`pointer-events-none absolute -top-10 -right-10 h-28 w-28 rounded-full ${item.glow} opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100`} />

              <div className="relative">
                <div className={`mb-4 flex h-10 w-10 items-center justify-center rounded-lg ${item.bg}`}>
                  <item.icon className={`h-5 w-5 ${item.color}`} />
                </div>
                <h3 className="text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {item.description}
                </p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
