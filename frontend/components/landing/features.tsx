"use client"

import { motion } from "motion/react"
import {
  Bot,
  Users,
  GitBranch,
  Shield,
  Plug,
  MessageSquare,
  FileText,
  KeyRound,
} from "lucide-react"

const features = [
  {
    icon: Bot,
    title: "Agent Builder",
    description:
      "Create AI agents with custom system prompts, tool configurations, model selection, and temperature controls. Fine-tune behavior for any use case.",
    color: "text-chart-1",
    bg: "bg-chart-1/10",
    glow: "bg-chart-1/20",
    border: "group-hover:border-chart-1/30",
  },
  {
    icon: Users,
    title: "Multi-Agent Teams",
    description:
      "Compose agents into collaborative teams that work together. Define team strategies, assign roles, and orchestrate multi-agent conversations.",
    color: "text-chart-2",
    bg: "bg-chart-2/10",
    glow: "bg-chart-2/20",
    border: "group-hover:border-chart-2/30",
  },
  {
    icon: GitBranch,
    title: "Workflow Automation",
    description:
      "Build complex multi-step workflows with conditional branching, loops, and agent handoffs. Schedule runs or trigger them via API.",
    color: "text-chart-5",
    bg: "bg-chart-5/10",
    glow: "bg-chart-5/20",
    border: "group-hover:border-chart-5/30",
  },
  {
    icon: Plug,
    title: "Any LLM Provider",
    description:
      "Connect OpenAI, Anthropic, Google, Azure, Groq, Ollama, or any OpenAI-compatible endpoint. Hot-swap providers without changing agent logic.",
    color: "text-chart-3",
    bg: "bg-chart-3/10",
    glow: "bg-chart-3/20",
    border: "group-hover:border-chart-3/30",
  },
  {
    icon: Shield,
    title: "Enterprise Security",
    description:
      "Role-based access control with granular permissions, two-factor authentication, and full audit logging. Built for production environments.",
    color: "text-chart-4",
    bg: "bg-chart-4/10",
    glow: "bg-chart-4/20",
    border: "group-hover:border-chart-4/30",
  },
  {
    icon: MessageSquare,
    title: "Real-time Playground",
    description:
      "Interactive chat interface with streaming responses, live tool call visualization, reasoning traces, and complete session history.",
    color: "text-chart-1",
    bg: "bg-chart-1/10",
    glow: "bg-chart-1/20",
    border: "group-hover:border-chart-1/30",
  },
  {
    icon: FileText,
    title: "File & Image Support",
    description:
      "Attach documents and images to conversations. Agents can process, analyze, and reference uploaded files throughout the session.",
    color: "text-chart-5",
    bg: "bg-chart-5/10",
    glow: "bg-chart-5/20",
    border: "group-hover:border-chart-5/30",
  },
  {
    icon: KeyRound,
    title: "Secrets Vault",
    description:
      "Fernet-encrypted secret storage with per-user isolation. Manage API keys, tokens, and credentials securely from the settings panel.",
    color: "text-chart-2",
    bg: "bg-chart-2/10",
    glow: "bg-chart-2/20",
    border: "group-hover:border-chart-2/30",
  },
]

export function Features() {
  return (
    <section id="features" className="relative py-0 sm:py-0">
      {/* Breathing background blobs */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute right-0 top-1/4 h-[500px] w-[500px] rounded-full bg-chart-1/4 blur-[160px]"
          animate={{ scale: [1, 1.15, 1], opacity: [0.3, 0.5, 0.3] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute left-0 bottom-1/4 h-[400px] w-[400px] rounded-full bg-chart-5/4 blur-[140px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.2, 0.4, 0.2] }}
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
            Everything you need to manage{" "}
            <span className="">
              AI agents
            </span>
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            A complete platform for building, deploying, and orchestrating intelligent agents at scale.
          </p>
        </motion.div>

        <div className="mx-auto mt-16 grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, i) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-50px" }}
              transition={{ duration: 0.4, delay: i * 0.06 }}
              className={`group relative overflow-hidden rounded-xl border border-border/50 bg-card/30 p-6 transition-all duration-300 hover:bg-card/60 ${feature.border}`}
            >
              {/* Hover glow */}
              <div className={`pointer-events-none absolute -top-12 -right-12 h-32 w-32 rounded-full ${feature.glow} opacity-0 blur-2xl transition-opacity duration-500 group-hover:opacity-100`} />

              <div className="relative">
                <div className={`mb-4 flex h-10 w-10 items-center justify-center rounded-lg ${feature.bg}`}>
                  <feature.icon className={`h-5 w-5 ${feature.color}`} />
                </div>
                <h3 className="text-sm font-semibold">{feature.title}</h3>
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {feature.description}
                </p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
