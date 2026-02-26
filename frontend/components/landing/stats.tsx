"use client"

import { motion, useInView } from "motion/react"
import { useRef, useEffect, useState } from "react"

const stats = [
  { value: 10, suffix: "+", label: "LLM Providers Supported", color: "from-chart-1 to-chart-1/60" },
  { value: 99.9, suffix: "%", label: "Uptime SLA", color: "from-chart-2 to-chart-2/60" },
  { value: 50, suffix: "ms", label: "Avg Streaming Latency", color: "from-chart-5 to-chart-5/60" },
  { value: 256, suffix: "-bit", label: "AES Encryption", color: "from-chart-4 to-chart-4/60" },
]

function AnimatedCounter({ value, suffix }: { value: number; suffix: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const isInView = useInView(ref, { once: true })
  const [display, setDisplay] = useState("0")

  useEffect(() => {
    if (!isInView) return
    const duration = 1500
    const start = Date.now()
    const isFloat = value % 1 !== 0

    const tick = () => {
      const elapsed = Date.now() - start
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = eased * value

      setDisplay(isFloat ? current.toFixed(1) : Math.round(current).toString())

      if (progress < 1) requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }, [isInView, value])

  return (
    <span ref={ref} className="tabular-nums">
      {display}{suffix}
    </span>
  )
}

export function Stats() {
  return (
    <section id="stats" className="relative py-24 sm:py-32">
      {/* Breathing background */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 h-[500px] w-[700px] rounded-full bg-chart-1/4 blur-[180px]"
          animate={{ scale: [1, 1.15, 1], opacity: [0.2, 0.45, 0.2] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.5 }}
          className="overflow-hidden rounded-2xl border border-border/50 bg-card/20 p-8 sm:p-12 backdrop-blur-sm"
        >
          {/* Inner decorative gradient line at top */}
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-chart-1/30 to-transparent" />

          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {stats.map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 10 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: i * 0.1 }}
                className="text-center"
              >
                <div className={`text-3xl font-bold tracking-tight sm:text-4xl bg-gradient-to-b`}>
                  <AnimatedCounter value={stat.value} suffix={stat.suffix} />
                </div>
                <div className="mt-2 text-sm text-muted-foreground">{stat.label}</div>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  )
}
