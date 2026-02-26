"use client"

import { useCallback, useState } from "react"
import { Copy, Check, ThumbsUp, ThumbsDown, Bot, FileText, BookOpen, FileCode2, Loader2, Wrench } from "lucide-react"
import { motion, AnimatePresence } from "motion/react"
import { usePlaygroundStore } from "@/stores/playground-store"
import { AppRoutes } from "@/app/api/routes"
import {
  Message,
  MessageContent,
  MessageResponse,
  MessageActions,
  MessageAction,
} from "@/components/ai-elements/message"
import { Reasoning } from "@/components/ai-elements/reasoning"
import { Tool, renderGenerativeUI, cleanToolName } from "@/components/ai-elements/tool"
import { Sources, SourceList, extractSourcesFromToolCalls } from "@/components/ai-elements/sources"
import { ResearchProgress } from "@/components/ai-elements/research-progress"
import { Terminal } from "@/components/ai-elements/terminal"
import { FileTree } from "@/components/ai-elements/file-tree"
import { Plan } from "@/components/ai-elements/plan"
import { JsxPreview } from "@/components/ai-elements/jsx-preview"
import { HITLApproval } from "@/components/ai-elements/hitl-approval"
import { ToolProposalCard } from "@/components/ai-elements/tool-proposal-card"
import type { Message as MessageType, ToolCall, ToolRound, FileNode, PlanData, HITLApprovalEvent, ToolProposalEvent } from "@/types/playground"

/** Extract the first html/jsx/tsx fenced block from message content.
 *  Returns { preview, stripped } where stripped has the fence block removed. */
function extractInlinePreview(content: string): { preview: string; stripped: string } | null {
  const fenceRe = /```(html|jsx|tsx)\n([\s\S]*?)```/
  const match = content.match(fenceRe)
  if (!match) return null
  const preview = match[2].trim()
  if (!preview) return null
  const stripped = content.replace(match[0], "").trim()
  return { preview, stripped }
}

const ARTIFACT_TAG_RE = /<artifact\s+([^>]*)>([\s\S]*?)<\/artifact>/g
const ARTIFACT_PATCH_RE = /<artifact_patch\s+[^>]*>[\s\S]*?<\/artifact_patch>/g
const ARTIFACT_ATTR_RE = /(\w[\w-]*)\s*=\s*"([^"]*)"/g

interface ArtifactRef { id: string; title: string; type: string }

/** Strip artifact and artifact_patch XML tags from content and extract artifact attributes. */
function stripArtifacts(content: string): { text: string; refs: ArtifactRef[] } {
  const refs: ArtifactRef[] = []
  const text = content
    .replace(ARTIFACT_TAG_RE, (_, attrs) => {
      const attrMap: Record<string, string> = {}
      let m: RegExpExecArray | null
      const re = new RegExp(ARTIFACT_ATTR_RE.source, "g")
      while ((m = re.exec(attrs)) !== null) attrMap[m[1]] = m[2]
      if (attrMap.id) refs.push({ id: attrMap.id, title: attrMap.title ?? "Artifact", type: attrMap.type ?? "text" })
      return ""
    })
    .replace(ARTIFACT_PATCH_RE, "")
    .trim()
  return { text, refs }
}

/** Inline chip that opens the artifact in the side panel */
function ArtifactRefPill({ artifactRef }: { artifactRef: ArtifactRef }) {
  const setActiveArtifactId = usePlaygroundStore((s) => s.setActiveArtifactId)
  const setArtifactPanelOpen = usePlaygroundStore((s) => s.setArtifactPanelOpen)
  return (
    <button
      onClick={() => { setActiveArtifactId(artifactRef.id); setArtifactPanelOpen(true) }}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-border bg-muted/40 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
    >
      <FileCode2 className="h-3 w-3 shrink-0" />
      <span>{artifactRef.title}</span>
      <span className="text-[10px] font-mono text-muted-foreground/70">{artifactRef.type}</span>
    </button>
  )
}

interface MessageBubbleProps {
  message: MessageType
  isStreaming?: boolean
  toolCalls?: ToolCall[]
  toolRound?: ToolRound | null
  kbContext?: { id: string; name: string }[]
  // AI Elements
  terminalOutput?: string
  terminalComplete?: boolean
  fileTree?: FileNode[] | null
  sourceUrls?: { url: string; title?: string }[]
  plan?: PlanData | null
  jsxPreview?: string
  jsxComplete?: boolean
  // HITL
  hitlApprovalEvent?: HITLApprovalEvent | null
  // Tool Proposals
  toolProposalEvent?: ToolProposalEvent | null
  generatingTool?: { name: string; handler_type: string } | null
  accessToken?: string
  onHITLResolved?: () => void
  onToolProposalResolved?: () => void
}

export function MessageBubble({
  message,
  isStreaming,
  toolCalls,
  toolRound,
  kbContext,
  terminalOutput,
  terminalComplete,
  fileTree,
  sourceUrls,
  plan,
  jsxPreview,
  jsxComplete,
  hitlApprovalEvent,
  toolProposalEvent,
  generatingTool,
  accessToken,
  onHITLResolved,
  onToolProposalResolved,
}: MessageBubbleProps) {
  const isUser = message.role === "user"
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState<"up" | "down" | null>(message.rating ?? null)
  const mode = usePlaygroundStore((s) => s.mode)
  const agents = usePlaygroundStore((s) => s.agents)

  // Resolve agent name for team messages
  const agentName = !isUser && message.agent_id && mode === "team"
    ? agents.find((a) => a.id === message.agent_id)?.name
    : undefined

  const handleCopy = useCallback(() => {
    if (message.content) {
      navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [message.content])

  const handleFeedback = useCallback(async (type: "up" | "down") => {
    const newRating = feedback === type ? null : type
    setFeedback(newRating)
    try {
      await fetch(AppRoutes.RateMessage(message.id), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: newRating }),
      })
    } catch {
      setFeedback(feedback)
    }
  }, [feedback, message.id])

  const activeCalls = toolCalls || message.tool_calls || []
  const reasoningText = message.reasoning?.map((r) => r.content).join("\n") || ""
  const sources = !isUser && !isStreaming
    ? extractSourcesFromToolCalls(activeCalls)
    : []

  return (
    <Message from={isUser ? "user" : "assistant"}>
      <MessageContent>
        {/* Agent name badge (team mode) */}
        {agentName && (
          <div className="flex items-center gap-1.5 mb-1">
            <Bot className="size-3 text-blue-500" />
            <span className="text-[11px] font-medium text-blue-500">{agentName}</span>
          </div>
        )}

        {/* Reasoning / Thinking */}
        {reasoningText && (
          <Reasoning isStreaming={isStreaming}>{reasoningText}</Reasoning>
        )}

        {/* Research progress indicator (only show from round 2+) */}
        {isStreaming && toolRound && toolRound.round > 1 && (
          <ResearchProgress round={toolRound.round} maxRounds={toolRound.max_rounds} />
        )}

        {/* KB context pill */}
        {kbContext && kbContext.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {kbContext.map((kb) => (
              <div
                key={kb.id}
                className="flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-0.5 text-[11px] text-muted-foreground"
              >
                <BookOpen className="size-3 shrink-0" />
                <span>{kb.name}</span>
              </div>
            ))}
          </div>
        )}

        {/* Tool calls */}
        {activeCalls.length > 0 && (
          <div className="space-y-2">
            {activeCalls.map((tc) => (
              <Tool
                key={tc.id}
                name={tc.name}
                state={tc.status === "completed" ? "completed" : tc.status === "error" ? "error" : "running"}
                input={tc.arguments}
                output={tc.result}
              />
            ))}
          </div>
        )}

        {/* HITL Approval card */}
        {!isUser && hitlApprovalEvent && (
          <HITLApproval
            event={hitlApprovalEvent}
            accessToken={accessToken}
            onResolved={onHITLResolved}
          />
        )}

        {/* Tool generating indicator */}
        {!isUser && generatingTool && !toolProposalEvent && (
          <div className="flex items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-500/5 px-3 py-2.5 text-xs text-violet-600 dark:text-violet-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
            <Wrench className="h-3.5 w-3.5 shrink-0" />
            <span>Generating implementation for <span className="font-mono font-semibold">{generatingTool.name}</span>...</span>
          </div>
        )}

        {/* Tool Proposal card */}
        {!isUser && toolProposalEvent && (
          <ToolProposalCard
            event={toolProposalEvent}
            accessToken={accessToken ?? ""}
            onResolved={onToolProposalResolved ?? (() => {})}
          />
        )}

        {/* Generative UI — rendered outside tool blocks */}
        {activeCalls
          .filter((tc) => tc.status === "completed" && tc.result)
          .map((tc) => {
            const { displayName } = cleanToolName(tc.name)
            const ui = renderGenerativeUI(displayName, tc.result!)
            return ui ? <div key={`genui_${tc.id}`}>{ui}</div> : null
          })}

        {/* Attachments */}
        {message.attachments && message.attachments.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {message.attachments.map((att, i) => (
              att.file_type === "image" ? (
                <img
                  key={i}
                  src={att.data || att.url}
                  alt={att.filename}
                  className="max-h-48 rounded-lg border border-border object-contain cursor-pointer hover:opacity-90 transition-opacity"
                  onClick={() => {
                    const src = att.data || att.url
                    if (src) window.open(src, "_blank")
                  }}
                />
              ) : (
                <div
                  key={i}
                  className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs"
                >
                  <FileText className="size-4 text-muted-foreground shrink-0" />
                  <span className="text-muted-foreground truncate max-w-40">{att.filename}</span>
                </div>
              )
            ))}
          </div>
        )}

        {/* Message content */}
        {message.content ? (
          isUser ? (
            <p className="text-sm whitespace-pre-wrap">{message.content.replace(/^\[EDIT ARTIFACT\s+[^\]]*\]\n?/, "")}</p>
          ) : isStreaming ? (
            <p className="text-sm whitespace-pre-wrap">
              {jsxPreview
                ? (extractInlinePreview(message.content)?.stripped ?? message.content.replace(/```(html|jsx|tsx)[\s\S]*$/, "").trim())
                : stripArtifacts(message.content.replace(/<artifact(?:_patch)?\s[^>]*>[\s\S]*$/, "")).text}
              <span className="inline-block h-4 w-0.5 bg-foreground animate-pulse ml-0.5 align-middle" />
            </p>
          ) : (() => {
            const { text, refs } = stripArtifacts(message.content)
            const inlinePreview = !refs.length ? extractInlinePreview(text) : null
            const displayText = inlinePreview ? inlinePreview.stripped : text
            return (
              <>
                {displayText && <MessageResponse>{displayText}</MessageResponse>}
                {inlinePreview && <JsxPreview jsx={inlinePreview.preview} />}
                {refs.map((ref) => (
                  <ArtifactRefPill key={ref.id} artifactRef={ref} />
                ))}
              </>
            )
          })()
        ) : null}

        {/* AI Elements — Terminal */}
        {terminalOutput && (
          <Terminal
            output={terminalOutput}
            isStreaming={isStreaming && !terminalComplete}
          />
        )}

        {/* AI Elements — File Tree */}
        {fileTree && fileTree.length > 0 && <FileTree nodes={fileTree} />}

        {/* AI Elements — Plan */}
        {plan && <Plan plan={plan} isStreaming={isStreaming && !plan.isComplete} />}

        {/* AI Elements — JSX Preview */}
        {jsxPreview && (
          <JsxPreview jsx={jsxPreview} isStreaming={isStreaming && !jsxComplete} />
        )}

        {/* AI Elements — SSE Source URLs */}
        {sourceUrls && sourceUrls.length > 0 && <SourceList sources={sourceUrls} />}

        {/* Sources from tool calls */}
        {sources.length > 0 && <Sources sources={sources} />}

        {/* Streaming cursor when no content yet */}
        {isStreaming && !message.content && activeCalls.length === 0 && !reasoningText && !hitlApprovalEvent && !toolProposalEvent && !generatingTool && (
          <div className="flex items-center gap-1.5 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-foreground/60 animate-bounce [animation-delay:0ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-foreground/60 animate-bounce [animation-delay:150ms]" />
            <span className="h-1.5 w-1.5 rounded-full bg-foreground/60 animate-bounce [animation-delay:300ms]" />
          </div>
        )}
      </MessageContent>

      {/* Actions (assistant messages only, not while streaming) */}
      {!isUser && !isStreaming && message.content && (
        <MessageActions>
          <MessageAction tooltip="Copy" onClick={handleCopy}>
            <AnimatePresence mode="wait">
              {copied ? (
                <motion.span
                  key="check"
                  initial={{ opacity: 0, scale: 0.5 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.5 }}
                  transition={{ type: "spring", stiffness: 300, damping: 20 }}
                >
                  <Check className="size-3.5 text-emerald-500" />
                </motion.span>
              ) : (
                <motion.span
                  key="copy"
                  initial={{ opacity: 0, scale: 0.5 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.5 }}
                  transition={{ type: "spring", stiffness: 300, damping: 20 }}
                >
                  <Copy className="size-3.5" />
                </motion.span>
              )}
            </AnimatePresence>
          </MessageAction>
          <MessageAction
            tooltip="Helpful"
            onClick={() => handleFeedback("up")}
            className={feedback === "up" ? "text-green-500 hover:text-green-500" : ""}
          >
            <ThumbsUp className="size-3.5" />
          </MessageAction>
          <MessageAction
            tooltip="Not helpful"
            onClick={() => handleFeedback("down")}
            className={feedback === "down" ? "text-red-500 hover:text-red-500" : ""}
          >
            <ThumbsDown className="size-3.5" />
          </MessageAction>
        </MessageActions>
      )}

      {/* Metadata */}
      {message.metadata && !isStreaming && !isUser && (
        <div className="text-[10px] text-muted-foreground flex items-center gap-2">
          {message.metadata.model && <span>{message.metadata.model}</span>}
          {(message.metadata.input_tokens != null || message.metadata.output_tokens != null) && (
            <span className="tabular-nums">
              ↑{message.metadata.input_tokens ?? 0} ↓{message.metadata.output_tokens ?? 0}
            </span>
          )}
          {message.metadata.latency_ms && (
            <span>{(message.metadata.latency_ms / 1000).toFixed(1)}s</span>
          )}
        </div>
      )}
    </Message>
  )
}
