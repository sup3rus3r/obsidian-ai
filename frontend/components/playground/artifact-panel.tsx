"use client"

import { useState, useCallback, useEffect, useRef } from "react"
import {
  X, Code2, Eye, Edit3, Copy, Check, Download,
  Maximize2, Minimize2, FileCode2,
} from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"
import { usePlaygroundStore } from "@/stores/playground-store"
import type { Artifact, ArtifactType } from "@/types/playground"

// KaTeX CSS — loaded once
let katexCssLoaded = false
function ensureKatexCss() {
  if (katexCssLoaded || typeof document === "undefined") return
  katexCssLoaded = true
  const link = document.createElement("link")
  link.rel = "stylesheet"
  link.href = "https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css"
  document.head.appendChild(link)
}

// ── Helpers ─────────────────────────────────────────────────────────────────

// Max characters to pass to Shiki — WASM onig engine can crash on very large inputs
const SHIKI_MAX_CHARS = 100_000

function useHighlightedCode(code: string, lang: string, skip = false) {
  const [html, setHtml] = useState("")
  useEffect(() => {
    if (skip || !code || code.length > SHIKI_MAX_CHARS) { setHtml(""); return }
    let cancelled = false
    const SUPPORTED = ["html","jsx","tsx","css","javascript","typescript","python","json","svg","markdown"] as const
    type SupportedLang = typeof SUPPORTED[number]
    if (!(SUPPORTED as readonly string[]).includes(lang)) { setHtml(""); return }
    const shikiLang = lang as SupportedLang
    import("shiki").then(({ createHighlighter }) =>
      createHighlighter({ themes: ["github-dark"], langs: [shikiLang] })
    ).then((hl) => {
      if (cancelled) return
      try { setHtml(hl.codeToHtml(code, { lang: shikiLang, theme: "github-dark" })) }
      catch { setHtml("") }
    }).catch(() => { if (!cancelled) setHtml("") })
    return () => { cancelled = true }
  }, [code, lang, skip])
  return html
}

function buildPreviewDoc(content: string, type: ArtifactType): string {
  const lower = content.trimStart().toLowerCase()
  if (lower.startsWith("<!doctype") || lower.startsWith("<html")) return content
  if (type === "html" || type === "svg") {
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>body{margin:16px;font-family:system-ui,sans-serif;font-size:14px}*{box-sizing:border-box}</style>
</head><body>${content}</body></html>`
  }
  if (type === "css") {
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/><style>${content}</style></head>
<body><div class="preview-root"><p>CSS applied to this page</p></div></body></html>`
  }
  if (type === "javascript" || type === "typescript") {
    // Run JS in a sandboxed iframe, capturing console output
    const escaped = content.replace(/`/g, "\\`").replace(/\\/g, "\\\\").replace(/\$/g, "\\$")
    return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<style>body{margin:0;background:#0d1117;color:#e6edf3;font-family:monospace;font-size:13px}
#out{padding:16px;white-space:pre-wrap;word-break:break-all}
.err{color:#f85149}.log{color:#e6edf3}.warn{color:#d29922}.info{color:#58a6ff}</style>
</head><body><div id="out"></div><script>
const out=document.getElementById('out');
const _log=(cls,...a)=>{const d=document.createElement('div');d.className=cls;d.textContent=a.map(x=>typeof x==='object'?JSON.stringify(x,null,2):String(x)).join(' ');out.appendChild(d)};
const _c={log:(...a)=>_log('log',...a),error:(...a)=>_log('err',...a),warn:(...a)=>_log('warn',...a),info:(...a)=>_log('info',...a)};
window.console=_c;
window.onerror=(m,_,l,c)=>{_log('err',\`Error (line \${l}:\${c}): \${m}\`);return true};
try{eval(\`${escaped}\`)}catch(e){_log('err',String(e))}
<\/script></body></html>`
  }
  return content
}

function LatexPreview({ content }: { content: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ensureKatexCss()
    import("katex").then(({ default: katex }) => {
      if (!ref.current) return
      // Render block math $$...$$ and inline $...$
      const html = content
        .replace(/\$\$([\s\S]+?)\$\$/g, (_, math) => {
          try { return katex.renderToString(math.trim(), { displayMode: true, throwOnError: false }) }
          catch { return `<span class="katex-err">${math}</span>` }
        })
        .replace(/\$([^$\n]+?)\$/g, (_, math) => {
          try { return katex.renderToString(math.trim(), { displayMode: false, throwOnError: false }) }
          catch { return `<span class="katex-err">${math}</span>` }
        })
        // Render \[...\] and \(...\) as well
        .replace(/\\\[([\s\S]+?)\\\]/g, (_, math) => {
          try { return katex.renderToString(math.trim(), { displayMode: true, throwOnError: false }) }
          catch { return `<span class="katex-err">${math}</span>` }
        })
        .replace(/\\\(([\s\S]+?)\\\)/g, (_, math) => {
          try { return katex.renderToString(math.trim(), { displayMode: false, throwOnError: false }) }
          catch { return `<span class="katex-err">${math}</span>` }
        })
      ref.current.innerHTML = html
    }).catch(() => {
      if (ref.current) ref.current.textContent = content
    })
  }, [content])
  return (
    <div
      ref={ref}
      className="h-full overflow-auto p-6 bg-background text-foreground text-sm leading-relaxed [&_.katex-display]:my-4 [&_.katex-err]:text-red-400 [&_.katex-err]:font-mono [&_.katex-err]:text-xs"
    />
  )
}

function isWebPreview(type: ArtifactType): boolean {
  return ["html", "jsx", "tsx", "svg", "css", "javascript", "typescript"].includes(type)
}

function isPreviewable(type: ArtifactType): boolean {
  return isWebPreview(type) || type === "markdown" || type === "text" || type === "json" || type === "latex"
}

type PanelTab = "preview" | "code" | "edit"

// ── Artifact tab pill ────────────────────────────────────────────────────────

function ArtifactTab({
  artifact, isActive, onClick, onClose,
}: { artifact: Artifact; isActive: boolean; onClick: () => void; onClose: () => void }) {
  return (
    <div
      role="button"
      onClick={onClick}
      className={cn(
        "group flex items-center gap-1 pl-2.5 pr-1 py-1.5 text-xs rounded-md font-medium transition-colors shrink-0 max-w-40 cursor-pointer select-none",
        isActive
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
      )}
    >
      <FileCode2 className="h-3 w-3 shrink-0" />
      <span className="truncate flex-1">{artifact.title}</span>
      <button
        onClick={(e) => { e.stopPropagation(); onClose() }}
        className="shrink-0 ml-0.5 p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-muted/60 hover:text-foreground transition-opacity"
        title="Close artifact"
      >
        <X className="h-2.5 w-2.5" />
      </button>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────

export function ArtifactPanel() {
  const artifacts = usePlaygroundStore((s) => s.artifacts)
  const activeArtifactId = usePlaygroundStore((s) => s.activeArtifactId)
  const artifactPanelOpen = usePlaygroundStore((s) => s.artifactPanelOpen)
  const streamingArtifact = usePlaygroundStore((s) => s.streamingArtifact)
  const setActiveArtifactId = usePlaygroundStore((s) => s.setActiveArtifactId)
  const setArtifactPanelOpen = usePlaygroundStore((s) => s.setArtifactPanelOpen)
  const updateArtifactContent = usePlaygroundStore((s) => s.updateArtifactContent)
  const removeArtifact = usePlaygroundStore((s) => s.removeArtifact)

  const [panelTab, setPanelTab] = useState<PanelTab>("preview")
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const editRef = useRef<HTMLTextAreaElement>(null)

  // Use streaming artifact when it matches the active id, or fall back to completed artifacts
  const completedArtifact = artifacts.find((a) => a.id === activeArtifactId) ?? artifacts[artifacts.length - 1] ?? null
  const isStreamingActive = !!streamingArtifact
  // isPatchEdit: streaming artifact matches an existing completed artifact — we're patching, not creating
  const isPatchEdit = isStreamingActive && !!artifacts.find((a) => a.id === streamingArtifact!.id)
  // Show streaming content if we have a streaming artifact (even before it's complete)
  const artifact = isStreamingActive
    ? { ...streamingArtifact, sessionId: "", createdAt: "", updatedAt: "" }
    : completedArtifact

  // Switch to code view for non-previewable types or while streaming
  useEffect(() => {
    if (isStreamingActive) {
      setPanelTab("code")
    } else if (artifact && !isPreviewable(artifact.type) && panelTab === "preview") {
      setPanelTab("code")
    }
  }, [artifact?.type, isStreamingActive])

  const highlightedHtml = useHighlightedCode(artifact?.content ?? "", artifact?.type ?? "text", isStreamingActive)
  const previewDoc = artifact && isWebPreview(artifact.type) ? buildPreviewDoc(artifact.content, artifact.type) : ""

  const handleCopy = useCallback(() => {
    if (!artifact) return
    navigator.clipboard.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [artifact])

  const handleDownload = useCallback(() => {
    if (!artifact) return
    const extMap: Record<ArtifactType, string> = {
      html: "html", jsx: "jsx", tsx: "tsx", css: "css",
      javascript: "js", typescript: "ts", python: "py",
      markdown: "md", text: "txt", json: "json", svg: "svg", latex: "tex",
    }
    const blob = new Blob([artifact.content], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${artifact.title.replace(/\s+/g, "_").toLowerCase()}.${extMap[artifact.type] ?? "txt"}`
    a.click()
    URL.revokeObjectURL(url)
  }, [artifact])

  if (!artifactPanelOpen || (!artifact && !streamingArtifact)) return null

  const canPreview = artifact ? isPreviewable(artifact.type) : false
  const canWebPreview = artifact ? isWebPreview(artifact.type) : false

  return (
    <div
      className={cn(
        "flex flex-col border-l border-border bg-background transition-all duration-200 overflow-hidden",
        expanded ? "fixed inset-0 z-50" : "h-full",
      )}
      style={expanded ? undefined : { width: "min(50%, 640px)", minWidth: "320px" }}
    >
      {/* Header row: artifact tabs — full width, scrollable */}
      <div className="flex items-center h-12 px-2 border-b border-border bg-muted/20 shrink-0 overflow-x-auto scrollbar-none">
        {artifacts.map((a) => (
          <div key={a.id} className="relative shrink-0">
            <ArtifactTab
              artifact={a}
              isActive={a.id === (isStreamingActive ? streamingArtifact!.id : artifact?.id)}
              onClick={() => setActiveArtifactId(a.id)}
              onClose={() => removeArtifact(a.id)}
            />
            {/* Patching indicator on active tab */}
            {isPatchEdit && a.id === streamingArtifact!.id && (
              <span className="absolute top-1 right-1 flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500" />
              </span>
            )}
          </div>
        ))}
        {/* Streaming tab — shown while agent is writing a new artifact */}
        {isStreamingActive && !isPatchEdit && (
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md font-medium bg-background text-foreground shadow-sm shrink-0 max-w-48">
            <FileCode2 className="h-3 w-3 shrink-0 text-amber-500" />
            <span className="truncate">{streamingArtifact!.title}</span>
            <span className="flex gap-0.5 ml-0.5 shrink-0">
              <span className="h-1 w-1 rounded-full bg-amber-400 animate-bounce [animation-delay:0ms]" />
              <span className="h-1 w-1 rounded-full bg-amber-400 animate-bounce [animation-delay:150ms]" />
              <span className="h-1 w-1 rounded-full bg-amber-400 animate-bounce [animation-delay:300ms]" />
            </span>
          </div>
        )}
      </div>

      {/* Toolbar: view tabs + actions + expand/close */}
      <div className="flex items-center gap-0 px-1 border-b border-border bg-muted/10 shrink-0">
        {/* View mode tabs */}
        {canPreview && (
          <button
            onClick={() => !isStreamingActive && setPanelTab("preview")}
            disabled={isStreamingActive}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors",
              panelTab === "preview" ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              isStreamingActive && "opacity-40 cursor-not-allowed",
            )}
          >
            <Eye className="h-3.5 w-3.5" />
            Preview
          </button>
        )}
        <button
          onClick={() => setPanelTab("code")}
          className={cn(
            "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors",
            panelTab === "code" ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          <Code2 className="h-3.5 w-3.5" />
          Code
        </button>
        <button
          onClick={() => {
            if (isStreamingActive) return
            setPanelTab("edit")
            setTimeout(() => editRef.current?.focus(), 50)
          }}
          disabled={isStreamingActive}
          className={cn(
            "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 transition-colors",
            panelTab === "edit" ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            isStreamingActive && "opacity-40 cursor-not-allowed",
          )}
        >
          <Edit3 className="h-3.5 w-3.5" />
          Edit
        </button>

        <div className="ml-auto flex items-center gap-0.5 pr-1">
          {/* Type badge */}
          {artifact && (
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground mr-1">
              {artifact.type}
            </span>
          )}
          <button
            onClick={handleCopy}
            title="Copy"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <button
            onClick={handleDownload}
            title="Download"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
          </button>
          <div className="w-px h-4 bg-border mx-1" />
          <button
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? "Restore" : "Expand"}
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            {expanded ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          <button
            onClick={() => setArtifactPanelOpen(false)}
            title="Close panel"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Patching status banner */}
      {isPatchEdit && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-500/10 border-b border-amber-500/20 text-[11px] text-amber-400 shrink-0">
          <span className="flex gap-0.5 shrink-0">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-bounce [animation-delay:0ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-bounce [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-bounce [animation-delay:300ms]" />
          </span>
          Applying patch…
        </div>
      )}

      {/* Content area */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {!artifact ? (
          <div className="flex items-center justify-center h-full text-xs text-muted-foreground">
            No artifact selected
          </div>
        ) : panelTab === "preview" && canPreview ? (
          artifact.type === "latex" ? (
            <LatexPreview content={artifact.content} />
          ) : canWebPreview ? (
            <iframe
              key={artifact.id + artifact.updatedAt}
              srcDoc={previewDoc}
              sandbox="allow-scripts"
              className="w-full h-full border-0 bg-white"
              title={artifact.title}
            />
          ) : (
            <div className="h-full overflow-auto p-6 bg-background">
              {artifact.type === "json" ? (
                <pre className="font-mono text-xs text-zinc-300 whitespace-pre-wrap wrap-break-word">
                  {(() => { try { return JSON.stringify(JSON.parse(artifact.content), null, 2) } catch { return artifact.content } })()}
                </pre>
              ) : (
                <div className="text-sm text-foreground leading-relaxed [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-4 [&_h1]:mt-6 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mb-3 [&_h2]:mt-5 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_p]:mb-3 [&_ul]:mb-3 [&_ul]:pl-5 [&_ul]:list-disc [&_ol]:mb-3 [&_ol]:pl-5 [&_ol]:list-decimal [&_li]:mb-1 [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:font-mono [&_code]:text-xs [&_pre]:bg-muted [&_pre]:p-3 [&_pre]:rounded [&_pre]:overflow-auto [&_pre]:mb-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_blockquote]:border-l-4 [&_blockquote]:border-border [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_blockquote]:mb-3 [&_hr]:border-border [&_hr]:mb-4 [&_a]:text-primary [&_a]:underline [&_strong]:font-semibold [&_table]:w-full [&_table]:mb-3 [&_th]:border [&_th]:border-border [&_th]:px-3 [&_th]:py-1.5 [&_th]:bg-muted [&_th]:text-left [&_td]:border [&_td]:border-border [&_td]:px-3 [&_td]:py-1.5">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {artifact.content}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          )
        ) : panelTab === "edit" ? (
          <textarea
            ref={editRef}
            value={artifact.content}
            onChange={(e) => updateArtifactContent(artifact.id, e.target.value)}
            className="w-full h-full resize-none bg-[#0d1117] text-zinc-300 font-mono text-xs p-4 outline-none border-0"
            spellCheck={false}
          />
        ) : (
          /* Code view */
          <div className="h-full overflow-auto bg-[#0d1117]">
            {highlightedHtml ? (
              <div
                className="text-xs [&>pre]:p-4 [&>pre]:m-0 [&>pre]:overflow-visible [&>pre]:bg-transparent!"
                dangerouslySetInnerHTML={{ __html: highlightedHtml }}
              />
            ) : (
              <pre className="p-4 font-mono text-xs text-zinc-300 whitespace-pre-wrap wrap-break-word">
                {artifact.content}
                {isStreamingActive && (
                  <span className="inline-block h-3 w-0.5 bg-amber-400 animate-pulse ml-0.5 align-middle" />
                )}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
