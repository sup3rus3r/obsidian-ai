"use client"

import { Header } from "@/components/landing/header"
import { Hero } from "@/components/landing/hero"

export default function Landing() {
  return (
    <div className="min-h-screen overflow-y-auto">
      <Header />
      <main>
        <Hero />
      </main>
      <footer className="border-t border-border/20 py-6 text-center text-[11px] text-muted-foreground/40">
        © {new Date().getFullYear()} Obsidian AI — licensed under AGPL-3.0
      </footer>
    </div>
  )
}
