import { Calculator } from "lucide-react"

interface CalculatorData {
  result?: string
  error?: string
}

export function CalculatorCard({ data }: { data: CalculatorData }) {
  if (data.error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-600 dark:text-red-400">
        {data.error}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 flex items-center gap-3">
      <Calculator className="h-5 w-5 text-muted-foreground shrink-0" />
      <span className="font-mono text-2xl font-bold tracking-tight">
        {data.result ?? "—"}
      </span>
    </div>
  )
}
