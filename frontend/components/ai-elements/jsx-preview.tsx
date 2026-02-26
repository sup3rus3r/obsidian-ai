"use client"

import { useEffect, useState, useCallback } from "react"
import { AlertCircle, Code2, Eye, Maximize2, Download, Copy, Check, X } from "lucide-react"
import { cn } from "@/lib/utils"

type Tab = "code" | "preview"

interface JsxPreviewProps {
  jsx: string
  isStreaming?: boolean
  onError?: (err: Error) => void
  className?: string
}

/** Detect whether the content is plain HTML vs JSX/TSX */
function detectContentType(code: string): "html" | "tsx" | "jsx" {
  const trimmed = code.trimStart()
  if (
    trimmed.startsWith("<!DOCTYPE") ||
    trimmed.startsWith("<!doctype") ||
    trimmed.startsWith("<html") ||
    (/^<[a-zA-Z]/.test(trimmed) && !/^\s*(import|export|function|const|let|var|class)\b/.test(code))
  ) {
    return "html"
  }
  if (code.includes(": ") || code.includes("interface ") || code.includes("<T>") || code.includes(": React.")) {
    return "tsx"
  }
  return "jsx"
}

/** True if the string is a complete HTML document */
function isCompleteHtmlDoc(code: string): boolean {
  const t = code.trimStart().toLowerCase()
  return t.startsWith("<!doctype") || t.startsWith("<html")
}

function buildPreviewDoc(jsx: string): string {
  if (isCompleteHtmlDoc(jsx)) return jsx
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  body { margin: 16px; font-family: system-ui, sans-serif; font-size: 14px; }
  * { box-sizing: border-box; }
</style>
</head>
<body>
${jsx}
</body>
</html>`
}

function useHighlightedCode(code: string, lang: string) {
  const [html, setHtml] = useState<string>("")

  useEffect(() => {
    if (!code) { setHtml(""); return }
    let cancelled = false
    const shikiLang = lang === "html" ? "html" : lang === "tsx" ? "tsx" : "jsx"
    import("shiki").then(({ createHighlighter }) =>
      createHighlighter({ themes: ["github-dark"], langs: [shikiLang as "html" | "tsx" | "jsx"] })
    ).then((highlighter) => {
      if (cancelled) return
      try {
        const result = highlighter.codeToHtml(code, { lang: shikiLang, theme: "github-dark" })
        setHtml(result)
      } catch {
        setHtml("")
      }
    }).catch(() => {
      if (!cancelled) setHtml("")
    })
    return () => { cancelled = true }
  }, [code, lang])

  return html
}

/** Shared tab bar used in both inline and fullscreen views */
function TabBar({
  activeTab,
  setActiveTab,
  codeLabel,
  isStreaming,
  onExpand,
  onCopy,
  onDownload,
  copied,
  isFullscreen = false,
  onClose,
}: {
  activeTab: Tab
  setActiveTab: (t: Tab) => void
  codeLabel: string
  isStreaming?: boolean
  onExpand?: () => void
  onCopy: () => void
  onDownload: () => void
  copied: boolean
  isFullscreen?: boolean
  onClose?: () => void
}) {
  return (
    <div className="flex items-center gap-0 border-b border-border bg-muted/30 px-1 shrink-0">
      <button
        onClick={() => setActiveTab("code")}
        className={cn(
          "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors",
          activeTab === "code"
            ? "border-primary text-foreground"
            : "border-transparent text-muted-foreground hover:text-foreground"
        )}
      >
        <Code2 className="h-3.5 w-3.5" />
        {codeLabel}
      </button>
      <button
        onClick={() => setActiveTab("preview")}
        className={cn(
          "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors",
          activeTab === "preview"
            ? "border-primary text-foreground"
            : "border-transparent text-muted-foreground hover:text-foreground"
        )}
      >
        <Eye className="h-3.5 w-3.5" />
        Preview
      </button>

      <div className="ml-auto flex items-center gap-0.5 pr-1">
        {isStreaming && (
          <span className="mr-1.5 text-[10px] text-blue-500 font-medium animate-pulse">
            streaming...
          </span>
        )}

        {/* Copy source */}
        <button
          onClick={onCopy}
          title="Copy source"
          className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
        </button>

        {/* Download file */}
        <button
          onClick={onDownload}
          title="Download file"
          className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        >
          <Download className="h-3.5 w-3.5" />
        </button>

        {/* Expand / Close */}
        {isFullscreen ? (
          <button
            onClick={onClose}
            title="Close"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : (
          <button
            onClick={onExpand}
            title="Expand"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  )
}

/** Code panel — shared between inline and fullscreen */
function CodePanel({ highlightedHtml, jsx, isStreaming }: { highlightedHtml: string; jsx: string; isStreaming?: boolean }) {
  return (
    <div className="flex-1 overflow-auto bg-[#0d1117]">
      {highlightedHtml ? (
        <div
          className="text-xs [&>pre]:p-4 [&>pre]:m-0 [&>pre]:overflow-visible [&>pre]:bg-transparent!"
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      ) : (
        <pre className="p-4 font-mono text-xs text-zinc-300 whitespace-pre-wrap wrap-break-word">
          {jsx}
          {isStreaming && (
            <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-zinc-300 align-middle" />
          )}
        </pre>
      )}
    </div>
  )
}

/** Preview iframe panel */
function PreviewPanel({ previewDoc, iframeError, onError }: { previewDoc: string; iframeError: string | null; onError: () => void }) {
  return (
    <div className="flex-1 bg-white">
      {iframeError ? (
        <div className="flex items-center gap-2 p-4 text-destructive text-xs">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {iframeError}
        </div>
      ) : (
        <iframe
          srcDoc={previewDoc}
          sandbox="allow-scripts"
          className="w-full h-full min-h-40 border-0"
          title="Preview"
          onError={onError}
        />
      )}
    </div>
  )
}

export function JsxPreview({ jsx, isStreaming = false, onError, className }: JsxPreviewProps) {
  const [activeTab, setActiveTab] = useState<Tab>("preview")
  const [iframeError, setIframeError] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [copied, setCopied] = useState(false)

  const contentType = detectContentType(jsx)
  const highlightedHtml = useHighlightedCode(jsx, contentType)
  const previewDoc = buildPreviewDoc(jsx)
  const codeLabel = contentType === "html" ? "HTML" : contentType === "tsx" ? "TSX" : "JSX"
  const ext = contentType === "html" ? "html" : contentType === "tsx" ? "tsx" : "jsx"

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(jsx)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [jsx])

  const handleDownload = useCallback(() => {
    const blob = new Blob([jsx], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `preview.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }, [jsx, ext])

  const sharedTabBarProps = {
    activeTab,
    setActiveTab: (t: Tab) => { setActiveTab(t); setIframeError(null) },
    codeLabel,
    isStreaming,
    onCopy: handleCopy,
    onDownload: handleDownload,
    copied,
  }

  return (
    <>
      {/* Inline card */}
      <div className={cn("rounded-lg border border-border overflow-hidden flex flex-col", className)}>
        <TabBar
          {...sharedTabBarProps}
          onExpand={() => setFullscreen(true)}
        />

        {activeTab === "code" ? (
          <div className="max-h-80">
            <CodePanel highlightedHtml={highlightedHtml} jsx={jsx} isStreaming={isStreaming} />
          </div>
        ) : (
          <div className="h-64">
            <PreviewPanel
              previewDoc={previewDoc}
              iframeError={iframeError}
              onError={() => setIframeError("Preview failed to load.")}
            />
          </div>
        )}
      </div>

      {/* Fullscreen overlay */}
      {fullscreen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-background">
          <TabBar
            {...sharedTabBarProps}
            isFullscreen
            onClose={() => setFullscreen(false)}
          />
          {activeTab === "code" ? (
            <CodePanel highlightedHtml={highlightedHtml} jsx={jsx} isStreaming={isStreaming} />
          ) : (
            <PreviewPanel
              previewDoc={previewDoc}
              iframeError={iframeError}
              onError={() => setIframeError("Preview failed to load.")}
            />
          )}
        </div>
      )}
    </>
  )
}
