"use client"

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { useState, useCallback, useEffect, useRef } from "react"
import { Check, Copy } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"

interface MarkdownRendererProps {
  content: string
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className || "")
          const isInline = !match

          if (isInline) {
            return (
              <code
                className="bg-muted px-1.5 py-0.5 rounded text-[13px] font-mono"
                {...props}
              >
                {children}
              </code>
            )
          }

          return (
            <CodeBlock language={match[1]}>
              {String(children).replace(/\n$/, "")}
            </CodeBlock>
          )
        },
        pre({ children }) {
          return <>{children}</>
        },
        a({ href, children }) {
          return (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 underline underline-offset-2 hover:text-blue-300"
            >
              {children}
            </a>
          )
        },
        table({ children }) {
          return (
            <div className="overflow-x-auto my-2">
              <table className="w-full border-collapse text-sm">{children}</table>
            </div>
          )
        },
        th({ children }) {
          return (
            <th className="border border-border px-3 py-1.5 text-left font-medium bg-muted">
              {children}
            </th>
          )
        },
        td({ children }) {
          return (
            <td className="border border-border px-3 py-1.5">{children}</td>
          )
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

function CodeBlock({
  children,
  language,
}: {
  children: string
  language: string
}) {
  const [copied, setCopied] = useState(false)
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null)
  const codeRef = useRef<HTMLDivElement>(null)

  const copy = useCallback(() => {
    navigator.clipboard.writeText(children)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [children])

  useEffect(() => {
    let cancelled = false
    async function highlight() {
      try {
        const { codeToHtml } = await import("shiki")
        const html = await codeToHtml(children, {
          lang: language,
          theme: "github-dark-default",
        })
        if (!cancelled) setHighlightedHtml(html)
      } catch {
        // Language not supported — fallback to plain text
        if (!cancelled) setHighlightedHtml(null)
      }
    }
    highlight()
    return () => { cancelled = true }
  }, [children, language])

  const lines = children.split("\n").length

  return (
    <div className="relative my-3 rounded-lg overflow-hidden bg-[#0d1117]">
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#161b22] border-b border-[#30363d]">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[#8b949e] font-mono">{language}</span>
          <span className="text-[10px] text-[#484f58]">{lines} line{lines !== 1 ? "s" : ""}</span>
        </div>
        <button
          onClick={copy}
          className="flex items-center gap-1 text-[11px] text-[#8b949e] hover:text-[#c9d1d9] transition-colors"
        >
          <AnimatePresence mode="wait">
            {copied ? (
              <motion.span
                key="copied"
                className="flex items-center gap-1"
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.15 }}
              >
                <Check className="h-3 w-3 text-emerald-400" /> Copied
              </motion.span>
            ) : (
              <motion.span
                key="copy"
                className="flex items-center gap-1"
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.15 }}
              >
                <Copy className="h-3 w-3" /> Copy
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      </div>
      {highlightedHtml ? (
        <div
          ref={codeRef}
          className="overflow-x-auto text-[13px] [&_pre]:!bg-transparent [&_pre]:p-4 [&_pre]:m-0 [&_code]:!bg-transparent"
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />
      ) : (
        <pre className="overflow-x-auto p-4">
          <code className="text-[13px] font-mono text-[#c9d1d9]">{children}</code>
        </pre>
      )}
    </div>
  )
}
