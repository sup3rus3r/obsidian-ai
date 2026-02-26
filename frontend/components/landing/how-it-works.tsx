"use client"

import { motion } from "motion/react"
import { Settings, Play, BarChart3 } from "lucide-react"

const steps = [
  {
    number: "01",
    icon: Settings,
    title: "Configure Your Agents",
    description:
      "Connect your preferred LLM providers, define agent personas with custom system prompts, attach tools, and configure MCP servers. Every detail is customizable from a single dashboard.",
    color: "text-chart-1",
    bg: "bg-chart-1/10",
    ring: "ring-chart-1/20",
    glow: "bg-chart-1/30",
    line: "from-chart-1/40 to-chart-1/0",
  },
  {
    number: "02",
    icon: Play,
    title: "Deploy & Orchestrate",
    description:
      "Launch individual agents or compose them into collaborative teams. Build automated workflows with conditional branching, loops, and agent handoffs that run on schedule or on demand.",
    color: "text-chart-5",
    bg: "bg-chart-5/10",
    ring: "ring-chart-5/20",
    glow: "bg-chart-5/30",
    line: "from-chart-5/40 to-chart-5/0",
  },
  {
    number: "03",
    icon: BarChart3,
    title: "Monitor & Iterate",
    description:
      "Track every session, message, and tool call in real time. Review conversation histories, analyze agent performance, and iterate on prompts and configurations to continuously improve results.",
    color: "text-chart-2",
    bg: "bg-chart-2/10",
    ring: "ring-chart-2/20",
    glow: "bg-chart-2/30",
    line: "from-chart-2/40 to-chart-2/0",
  },
]

export function HowItWorks() {
  return (
    <section id="how-it-works" className="relative py-24 sm:py-32">
      {/* Breathing background blobs */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute right-0 top-1/4 h-[500px] w-[500px] rounded-full bg-chart-5/5 blur-[160px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute left-0 bottom-0 h-[400px] w-[400px] rounded-full bg-chart-2/5 blur-[140px]"
          animate={{ scale: [1, 1.15, 1], opacity: [0.2, 0.5, 0.2] }}
          transition={{ duration: 12, repeat: Infinity, ease: "easeInOut", delay: 4 }}
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
            Up and running in{" "}
            <span className="">
              minutes
            </span>
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Three simple steps to go from zero to a fully orchestrated AI agent fleet.
          </p>
        </motion.div>

        <div className="mx-auto mt-20 max-w-4xl">
          {steps.map((step, i) => (
            <motion.div
              key={step.number}
              initial={{ opacity: 0, x: i % 2 === 0 ? -30 : 30 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true, margin: "-50px" }}
              transition={{ duration: 0.5, delay: i * 0.15 }}
              className="relative flex gap-6 pb-16 last:pb-0"
            >
              {/* Gradient vertical line connector */}
              {i < steps.length - 1 && (
                <div className={`absolute left-[23px] top-14 bottom-0 w-px bg-gradient-to-b ${step.line}`} />
              )}

              {/* Step icon circle with coloured ring + glow */}
              <div className="relative z-10 shrink-0">
                <div className={`absolute inset-0 rounded-full ${step.glow} blur-lg opacity-60`} />
                <div className={`relative flex h-12 w-12 items-center justify-center rounded-full ${step.bg} ring-1 ${step.ring}`}>
                  <step.icon className={`h-5 w-5 ${step.color}`} />
                </div>
              </div>

              {/* Content */}
              <div className="pt-1">
                <span className={`text-xs font-medium tracking-widest ${step.color}/70`}>
                  STEP {step.number}
                </span>
                <h3 className="mt-1 text-lg font-semibold">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground max-w-lg">
                  {step.description}
                </p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  )
}
