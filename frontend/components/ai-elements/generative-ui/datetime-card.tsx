import { Clock } from "lucide-react"

interface DateTimeData {
  datetime?: string
  timezone?: string
  error?: string
}

function formatDateTime(isoStr: string): { time: string; date: string } {
  try {
    const d = new Date(isoStr)
    const time = d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    })
    const date = d.toLocaleDateString("en-US", {
      weekday: "long",
      year: "numeric",
      month: "long",
      day: "numeric",
    })
    return { time, date }
  } catch {
    return { time: isoStr, date: "" }
  }
}

export function DateTimeCard({ data }: { data: DateTimeData }) {
  if (data.error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-600 dark:text-red-400">
        {data.error}
      </div>
    )
  }

  const { time, date } = data.datetime
    ? formatDateTime(data.datetime)
    : { time: "—", date: "" }

  return (
    <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 flex items-center gap-3">
      <Clock className="h-5 w-5 text-muted-foreground shrink-0" />
      <div>
        <p className="text-lg font-semibold tabular-nums tracking-tight">{time}</p>
        <p className="text-xs text-muted-foreground">
          {date}
          {data.timezone && data.timezone !== "UTC" && (
            <span className="ml-1 text-muted-foreground/70">· {data.timezone}</span>
          )}
          {data.timezone === "UTC" && (
            <span className="ml-1 text-muted-foreground/70">· UTC</span>
          )}
        </p>
      </div>
    </div>
  )
}
