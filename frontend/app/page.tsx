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
    </div>
  )
}
