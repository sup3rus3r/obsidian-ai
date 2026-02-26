import { Cloud, Droplets, Wind } from "lucide-react"

interface WeatherData {
  location?: string
  temperature_c?: number
  temperature_f?: number
  humidity_pct?: number
  wind_kmh?: number
  condition?: string
  error?: string
}

export function WeatherCard({ data }: { data: WeatherData }) {
  if (data.error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-600 dark:text-red-400">
        {data.error}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-sky-200 dark:border-sky-900/40 bg-gradient-to-br from-sky-50 to-blue-50 dark:from-sky-950/30 dark:to-blue-950/30 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          {data.location && (
            <p className="text-xs font-medium text-sky-600 dark:text-sky-400 truncate mb-1">
              {data.location}
            </p>
          )}
          <div className="flex items-end gap-2">
            {data.temperature_f != null && (
              <span className="text-4xl font-bold tracking-tight text-foreground">
                {data.temperature_f}°F
              </span>
            )}
            {data.temperature_c != null && (
              <span className="text-sm text-muted-foreground mb-1">
                {data.temperature_c}°C
              </span>
            )}
          </div>
          {data.condition && (
            <p className="text-sm text-muted-foreground mt-0.5">{data.condition}</p>
          )}
        </div>
        <Cloud className="h-12 w-12 text-sky-400 shrink-0 mt-1" />
      </div>

      {(data.humidity_pct != null || data.wind_kmh != null) && (
        <div className="mt-3 flex gap-4 border-t border-sky-200/60 dark:border-sky-800/40 pt-3">
          {data.humidity_pct != null && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Droplets className="h-3.5 w-3.5 text-sky-400" />
              <span>{data.humidity_pct}% humidity</span>
            </div>
          )}
          {data.wind_kmh != null && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Wind className="h-3.5 w-3.5 text-sky-400" />
              <span>{data.wind_kmh} km/h</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
