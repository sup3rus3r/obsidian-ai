import { Sparkles } from "lucide-react"

interface StatData {
  _ui_type?: string
  title?: string
  value?: string | number
  label?: string
  error?: string
}

export function StatCard({ data }: { data: StatData }) {
  if (data.error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-600 dark:text-red-400">
        {data.error}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-4">
      <div className="flex items-center gap-1.5 mb-1">
        <Sparkles className="h-3.5 w-3.5 text-muted-foreground" />
        {data.title && (
          <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider">
            {data.title}
          </p>
        )}
      </div>
      <p className="text-3xl font-bold tracking-tight mt-0.5">
        {data.value ?? "—"}
      </p>
      {data.label && (
        <p className="text-xs text-muted-foreground mt-1">{data.label}</p>
      )}
    </div>
  )
}
