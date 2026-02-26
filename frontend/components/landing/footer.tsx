"use client"

import { Cpu } from "lucide-react"

const footerLinks = [
  {
    title: "PRODUCT",
    links: [
      { label: "Features", href: "#features" },
      { label: "How It Works", href: "#how-it-works" },
      { label: "Integrations", href: "#integrations" },
      { label: "Platform", href: "#platform" },
    ],
  },
  {
    title: "DEVELOPERS",
    links: [
      { label: "API Access", href: "/login" },
      { label: "MCP Servers", href: "#platform" },
      { label: "Playground", href: "/login" },
    ],
  },
  {
    title: "COMPANY",
    links: [
      { label: "Sign In", href: "/login" },
      { label: "Register", href: "/register" },
    ],
  },
]

export function Footer() {
  return (
    <footer className="relative border-t border-border/50 overflow-hidden">
      {/* Subtle top glow */}
      <div className="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[300px] w-[600px] rounded-full bg-chart-1/3 blur-[160px]" />

      {/* Gradient border line */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-chart-1/20 to-transparent" />

      <div className="relative mx-auto max-w-7xl px-6 py-12">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
          {/* Brand column */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-chart-1/20 to-chart-5/20 ring-1 ring-chart-1/20">
                <Cpu className="h-3.5 w-3.5 text-chart-1" />
              </div>
              <span className="text-sm font-bold tracking-tight">Obsidian AI</span>
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground max-w-xs">
              The open-source AI agent control plane. Build, deploy, and orchestrate intelligent agents from a single dashboard.
            </p>
          </div>

          {/* Link columns */}
          {footerLinks.map((section) => (
            <div key={section.title}>
              <h4 className="text-xs font-medium tracking-widest text-muted-foreground mb-4">
                {section.title}
              </h4>
              <ul className="space-y-2.5">
                {section.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-chart-1"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-border/50 pt-8 sm:flex-row">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} Obsidian AI. All rights reserved.
          </p>
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs text-muted-foreground">All systems operational</span>
          </div>
        </div>
      </div>
    </footer>
  )
}
