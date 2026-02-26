import { ExternalLink, Search } from "lucide-react"

interface SearchResult {
  title?: string
  snippet?: string
  url?: string
}

interface SearchData {
  query?: string
  results?: SearchResult[]
  note?: string
  error?: string
}

export function SearchResultsCard({ data }: { data: SearchData }) {
  if (data.error) {
    return (
      <div className="rounded-lg border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/20 px-3 py-2 text-xs text-red-600 dark:text-red-400">
        {data.error}
      </div>
    )
  }

  const results = data.results ?? []

  return (
    <div className="rounded-lg border border-border bg-background overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-muted/30">
        <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
        {data.query && (
          <span className="text-xs text-muted-foreground truncate">
            Results for <span className="font-medium text-foreground">"{data.query}"</span>
          </span>
        )}
      </div>

      {results.length === 0 ? (
        <div className="px-3 py-3 text-xs text-muted-foreground italic">
          {data.note ?? "No results found."}
        </div>
      ) : (
        <div className="divide-y divide-border">
          {results.map((r, i) => (
            <div key={i} className="px-3 py-2.5 space-y-0.5 hover:bg-muted/20 transition-colors">
              {r.url ? (
                <a
                  href={r.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline w-fit max-w-full"
                >
                  <span className="truncate">{r.title || r.url}</span>
                  <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                </a>
              ) : (
                r.title && (
                  <p className="text-xs font-medium text-foreground truncate">{r.title}</p>
                )
              )}
              {r.snippet && (
                <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                  {r.snippet}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {data.note && results.length > 0 && (
        <div className="px-3 py-1.5 border-t border-border text-[10px] text-muted-foreground italic">
          {data.note}
        </div>
      )}
    </div>
  )
}
