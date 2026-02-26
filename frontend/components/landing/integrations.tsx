"use client"

import { motion } from "motion/react"
import { Badge } from "@/components/ui/badge"

const providers = [
  { name: "OpenAI", models: "GPT-5, GPT-4, o1, o3", color: "text-chart-1", bg: "bg-chart-1/8", border: "hover:border-chart-1/30", glow: "group-hover:shadow-chart-1/5" },
  { name: "Anthropic", models: "Claude 4, Sonnet, Haiku", color: "text-chart-5", bg: "bg-chart-5/8", border: "hover:border-chart-5/30", glow: "group-hover:shadow-chart-5/5" },
  { name: "Google", models: "Gemini 2.5 Pro, Flash", color: "text-chart-2", bg: "bg-chart-2/8", border: "hover:border-chart-2/30", glow: "group-hover:shadow-chart-2/5" },
  // { name: "Azure OpenAI", models: "All GPT models via Azure", color: "text-chart-1", bg: "bg-chart-1/8", border: "hover:border-chart-1/30", glow: "group-hover:shadow-chart-1/5" },
  // { name: "DeepSeek", models: "DeepSeek V3, R1", color: "text-chart-3", bg: "bg-chart-3/8", border: "hover:border-chart-3/30", glow: "group-hover:shadow-chart-3/5" },
  // { name: "Groq", models: "Llama, Mixtral, Gemma", color: "text-chart-4", bg: "bg-chart-4/8", border: "hover:border-chart-4/30", glow: "group-hover:shadow-chart-4/5" },
  // { name: "Mistral AI", models: "Mistral Large, Medium", color: "text-chart-5", bg: "bg-chart-5/8", border: "hover:border-chart-5/30", glow: "group-hover:shadow-chart-5/5" },
  // { name: "Ollama", models: "Any local model", color: "text-chart-2", bg: "bg-chart-2/8", border: "hover:border-chart-2/30", glow: "group-hover:shadow-chart-2/5" },
  { name: "OpenRouter", models: "200+ models, one API", color: "text-chart-1", bg: "bg-chart-1/8", border: "hover:border-chart-1/30", glow: "group-hover:shadow-chart-1/5" },
  // { name: "Together AI", models: "Open-source models", color: "text-chart-4", bg: "bg-chart-4/8", border: "hover:border-chart-4/30", glow: "group-hover:shadow-chart-4/5" },
  // { name: "Fireworks AI", models: "Fast open-source inference", color: "text-chart-5", bg: "bg-chart-5/8", border: "hover:border-chart-5/30", glow: "group-hover:shadow-chart-5/5" },
  { name: "Custom", models: "Any OpenAI-compatible API", color: "text-chart-3", bg: "bg-chart-3/8", border: "hover:border-chart-3/30", glow: "group-hover:shadow-chart-3/5" },
]

const capabilities = [
  { label: "Tool calling & function execution", color: "border-chart-1/20 text-chart-1/80 hover:bg-chart-1/10" },
  { label: "Streaming responses with reasoning traces", color: "border-chart-5/20 text-chart-5/80 hover:bg-chart-5/10" },
  { label: "Multi-agent team orchestration", color: "border-chart-2/20 text-chart-2/80 hover:bg-chart-2/10" },
  { label: "Automated multi-step workflows", color: "border-chart-4/20 text-chart-4/80 hover:bg-chart-4/10" },
  { label: "MCP server integration", color: "border-chart-3/20 text-chart-3/80 hover:bg-chart-3/10" },
  { label: "File & image attachments", color: "border-chart-1/20 text-chart-1/80 hover:bg-chart-1/10" },
  { label: "Session history & replay", color: "border-chart-5/20 text-chart-5/80 hover:bg-chart-5/10" },
  { label: "Role-based access control", color: "border-chart-2/20 text-chart-2/80 hover:bg-chart-2/10" },
  { label: "Encrypted secrets vault", color: "border-chart-4/20 text-chart-4/80 hover:bg-chart-4/10" },
  { label: "Two-factor authentication", color: "border-chart-3/20 text-chart-3/80 hover:bg-chart-3/10" },
  { label: "API client credentials", color: "border-chart-1/20 text-chart-1/80 hover:bg-chart-1/10" },
  { label: "Real-time dashboard analytics", color: "border-chart-5/20 text-chart-5/80 hover:bg-chart-5/10" },
]

export function Integrations() {
  return (
    <section id="integrations" className="relative py-24 sm:py-32">
      {/* Breathing background blobs */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute left-1/2 top-0 -translate-x-1/2 h-[600px] w-[600px] rounded-full bg-chart-1/4 blur-[180px]"
          animate={{ scale: [1, 1.1, 1], opacity: [0.2, 0.5, 0.2] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute right-0 bottom-1/3 h-[400px] w-[400px] rounded-full bg-chart-4/4 blur-[140px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.15, 0.4, 0.15] }}
          transition={{ duration: 14, repeat: Infinity, ease: "easeInOut", delay: 5 }}
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
            Works with{" "}
            <span className="">
              most major providers
            </span>
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">
            Connect any OpenAI-compatible LLM endpoint. Swap providers without touching a single line of agent logic.
          </p>
        </motion.div>

        {/* Provider grid */}
        <div className="mx-auto mt-16 grid max-w-5xl gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {providers.map((provider, i) => (
            <motion.div
              key={provider.name}
              initial={{ opacity: 0, scale: 0.95 }}
              whileInView={{ opacity: 1, scale: 1 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: i * 0.04 }}
              className={`group relative overflow-hidden rounded-lg border border-border/40 bg-card/20 px-4 py-3 transition-all duration-300 hover:bg-card/50 hover:shadow-lg ${provider.border} ${provider.glow}`}
            >
              {/* Subtle coloured dot */}
              <div className={`absolute top-3 right-3 h-1.5 w-1.5 rounded-full ${provider.bg} opacity-0 group-hover:opacity-100 transition-opacity`} />
              <div className={`text-sm font-semibold ${provider.color} transition-colors group-hover:text-foreground`}>{provider.name}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{provider.models}</div>
            </motion.div>
          ))}
        </div>

        {/* Capabilities */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-80px" }}
          transition={{ duration: 0.5 }}
          className="mx-auto mt-20 max-w-4xl"
        >
          <h3 className="text-center text-lg font-semibold mb-8">
            Full platform capabilities
          </h3>
          <div className="flex flex-wrap items-center justify-center gap-2">
            {capabilities.map((cap, i) => (
              <motion.div
                key={cap.label}
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.3, delay: i * 0.03 }}
              >
                <Badge
                  variant="outline"
                  className={`bg-card/20 px-3 py-1.5 text-xs font-normal transition-colors cursor-default`}
                >
                  {cap.label}
                </Badge>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}
