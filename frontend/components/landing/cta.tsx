"use client"

import { motion } from "motion/react"
import { Button } from "@/components/ui/button"
import { ArrowRight, Sparkles } from "lucide-react"
import { useRouter } from "next/navigation"

export function CTA() {
  const router = useRouter()

  return (
    <section className="relative py-24 sm:py-32">
      {/* Breathing background blobs */}
      <div className="pointer-events-none absolute inset-0">
        <motion.div
          className="absolute left-1/4 top-1/2 -translate-y-1/2 h-[500px] w-[500px] rounded-full bg-chart-1/5 blur-[160px]"
          animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="absolute right-1/4 top-1/2 -translate-y-1/2 h-[400px] w-[400px] rounded-full bg-chart-5/5 blur-[140px]"
          animate={{ scale: [1, 1.15, 1], opacity: [0.2, 0.5, 0.2] }}
          transition={{ duration: 10, repeat: Infinity, ease: "easeInOut", delay: 3 }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-100px" }}
          transition={{ duration: 0.5 }}
          className="relative mx-auto max-w-3xl overflow-hidden rounded-2xl border border-border/50 bg-card/20 p-10 sm:p-14 text-center backdrop-blur-sm"
        >
          {/* Decorative gradient lines */}
          <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-chart-1/40 to-transparent" />
          <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-chart-5/40 to-transparent" />

          {/* Corner glows */}
          <div className="pointer-events-none absolute -top-16 -left-16 h-40 w-40 rounded-full bg-chart-1/10 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-16 -right-16 h-40 w-40 rounded-full bg-chart-5/10 blur-3xl" />

          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            whileInView={{ opacity: 1, scale: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="relative"
          >
            <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-chart-1/20 to-chart-5/20 ring-1 ring-chart-1/20">
              <Sparkles className="h-6 w-6 text-chart-1" />
            </div>

            <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
              Ready to{" "}
              <span className="bg-gradient-to-r from-chart-1 via-chart-5 to-chart-2 bg-clip-text text-transparent">
                orchestrate
              </span>{" "}
              your AI agents?
            </h2>
            <p className="mt-4 text-lg text-muted-foreground">
              Get started in minutes. No credit card required. Deploy your first agent today.
            </p>
            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <Button
                size="lg"
                className="cursor-pointer gap-2 px-8 text-base"
                onClick={() => router.push("/register")}
              >
                Start Building
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button
                size="lg"
                variant="outline"
                className="cursor-pointer px-8 text-base"
                onClick={() => router.push("/login")}
              >
                Sign In
              </Button>
            </div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  )
}
