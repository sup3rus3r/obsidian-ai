import { Suspense } from "react"
import { PlaygroundShell } from "@/components/playground/playground-shell"

export default function PlaygroundLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <Suspense>
      <PlaygroundShell>{children}</PlaygroundShell>
    </Suspense>
  )
}
