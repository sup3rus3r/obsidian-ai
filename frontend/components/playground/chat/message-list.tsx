"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { MessageBubble } from "./message-bubble"
import { ScrollButton } from "@/components/ai-elements/scroll-button"
import type { Message, ToolCall, AgentStep, ToolRound, FileNode, PlanData, HITLApprovalEvent, ToolProposalEvent, ThreadContinueEvent, AgentThreadMessageRecord } from "@/types/playground"
import type { AgentHopEntry } from "@/stores/playground-store"

/** Group persisted agent-to-agent hops by their nearest following Message in
 *  the same session — there's no direct FK linking a hop to "the turn it was
 *  part of" (see AgentThreadMessage's docstring), so history reconstructs the
 *  association from timestamps instead: each hop belongs to whichever
 *  Message was saved immediately after it. */
function groupThreadMessagesByFollowingMessage(
  messages: Message[],
  threadMessages: AgentThreadMessageRecord[]
): Map<string, AgentHopEntry[]> {
  const result = new Map<string, AgentHopEntry[]>()
  if (threadMessages.length === 0) return result
  const sortedMessages = [...messages]
    .filter((m) => m.role !== "user")
    .map((m) => ({ id: m.id, time: new Date(m.created_at).getTime() }))
    .sort((a, b) => a.time - b.time)

  for (const hop of threadMessages) {
    const hopTime = new Date(hop.created_at).getTime()
    const owner = sortedMessages.find((m) => m.time >= hopTime)
    if (!owner) continue
    const [asked, response] = (hop.content ?? "").split("\n\n[Response]: ")
    const entry: AgentHopEntry = {
      thread_id: hop.thread_id,
      hop_index: hop.hop_index,
      from_agent_id: hop.from_agent_id,
      from_agent_name: hop.from_agent_name ?? "Agent",
      to_agent_id: hop.to_agent_id,
      to_agent_name: hop.to_agent_name ?? "Agent",
      message: asked?.replace(/^\[Asked\]: /, "") ?? "",
      response,
      status: "completed",
    }
    const list = result.get(owner.id) ?? []
    list.push(entry)
    result.set(owner.id, list)
  }
  for (const list of result.values()) list.sort((a, b) => a.hop_index - b.hop_index)
  return result
}

interface MessageListProps {
  messages: Message[]
  threadMessages?: AgentThreadMessageRecord[]
  streamingContent: string
  streamingReasoning: string
  streamingToolCalls: ToolCall[]
  streamingAgentStep?: AgentStep | null
  streamingAgentStepLog?: AgentStep[]
  streamingToolRound?: ToolRound | null
  streamingKBContext?: { id: string; name: string }[]
  isStreaming: boolean
  // AI Elements
  streamingTerminal?: string
  streamingTerminalComplete?: boolean
  streamingFileTree?: FileNode[] | null
  streamingSourceUrls?: { url: string; title?: string }[]
  streamingPlan?: PlanData | null
  streamingJsx?: string
  streamingJsxComplete?: boolean
  // HITL
  pendingHITLApproval?: HITLApprovalEvent | null
  // Open multi-agent delegation threads (call_teammate)
  streamingAgentHopLog?: AgentHopEntry[]
  pendingThreadContinue?: ThreadContinueEvent | null
  onThreadContinueResolved?: () => void
  // Tool Proposals
  pendingToolProposal?: ToolProposalEvent | null
  generatingTool?: { name: string; handler_type: string } | null
  accessToken?: string
  onHITLResolved?: () => void
  onToolProposalResolved?: () => void
}

export function MessageList({
  messages,
  threadMessages,
  streamingContent,
  streamingReasoning,
  streamingToolCalls,
  streamingAgentStep,
  streamingAgentStepLog,
  streamingToolRound,
  streamingKBContext,
  isStreaming,
  streamingTerminal,
  streamingTerminalComplete,
  streamingFileTree,
  streamingSourceUrls,
  streamingPlan,
  streamingJsx,
  streamingJsxComplete,
  pendingHITLApproval,
  streamingAgentHopLog,
  pendingThreadContinue,
  onThreadContinueResolved,
  pendingToolProposal,
  generatingTool,
  accessToken,
  onHITLResolved,
  onToolProposalResolved,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [showScrollButton, setShowScrollButton] = useState(false)

  // Track whether user is near bottom using scroll position
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const onScroll = () => {
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      const atBottom = distanceFromBottom < 80
      setIsAtBottom(atBottom)
      setShowScrollButton(!atBottom)
    }

    el.addEventListener("scroll", onScroll, { passive: true })
    return () => el.removeEventListener("scroll", onScroll)
  }, [])

  // Auto-scroll only when user is near the bottom
  useEffect(() => {
    const el = scrollRef.current
    if (isAtBottom && el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, streamingContent, streamingToolCalls, streamingReasoning, streamingAgentStep, streamingAgentStepLog, isAtBottom])

  const scrollToBottom = useCallback(() => {
    setIsAtBottom(true)
    setShowScrollButton(false)
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [])

  // Show the streaming bubble when there's any streaming activity or pending HITL
  const hasStreamingActivity =
    isStreaming &&
    (streamingContent ||
      streamingToolCalls.length > 0 ||
      streamingReasoning ||
      (streamingKBContext && streamingKBContext.length > 0) ||
      streamingTerminal ||
      (streamingFileTree && streamingFileTree.length > 0) ||
      (streamingSourceUrls && streamingSourceUrls.length > 0) ||
      streamingPlan ||
      streamingJsx ||
      pendingHITLApproval ||
      (streamingAgentHopLog && streamingAgentHopLog.length > 0) ||
      pendingThreadContinue ||
      pendingToolProposal ||
      generatingTool)

  const hopsByMessageId = groupThreadMessagesByFollowingMessage(messages, threadMessages ?? [])

  return (
    <div ref={scrollRef} className="relative flex-1 overflow-y-auto min-h-0">
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {messages.map((message) => {
          // Render compaction notice as a special divider
          if (message.role === "system" && message.content?.startsWith("__compacted__:")) {
            const count = message.content.split(":")[1]
            return (
              <div key={message.id} className="flex items-center gap-3 py-1">
                <div className="flex-1 h-px bg-border" />
                <span className="text-xs text-muted-foreground whitespace-nowrap">
                  Context compacted — {count} messages summarized
                </span>
                <div className="flex-1 h-px bg-border" />
              </div>
            )
          }
          // Skip other system messages
          if (message.role === "system") return null
          return <MessageBubble key={message.id} message={message} agentHopLog={hopsByMessageId.get(message.id)} />
        })}

        {/* Agent step indicator (team mode) — a running log when multiple steps have
            fired (route mode's parallel agents), otherwise a single pulsing line. */}
        {isStreaming && streamingAgentStepLog && streamingAgentStepLog.length > 1 ? (
          <div className="flex flex-col gap-1 px-2 py-1.5">
            {streamingAgentStepLog.map((step, i) => {
              const isLatest = i === streamingAgentStepLog.length - 1
              const isDone = step.step === "completed" || step.step === "selected"
              const isFailed = step.step === "failed"
              return (
                <div key={`${step.agent_id}-${step.step}-${i}`} className="flex items-center gap-2">
                  <span
                    className={
                      isFailed
                        ? "h-1.5 w-1.5 rounded-full bg-destructive"
                        : isDone
                        ? "h-1.5 w-1.5 rounded-full bg-emerald-500"
                        : isLatest
                        ? "h-1.5 w-1.5 rounded-full bg-primary animate-pulse"
                        : "h-1.5 w-1.5 rounded-full bg-muted-foreground/40"
                    }
                  />
                  <span className={isFailed ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                    {step.step === "routing" && "Routing query..."}
                    {step.step === "responding" && `${step.agent_name} is responding...`}
                    {step.step === "selected" && `Selected ${step.agent_name}${step.router_decision ? ` (${step.router_decision})` : ""}`}
                    {step.step === "completed" && `${step.agent_name} completed`}
                    {step.step === "failed" && `${step.agent_name} failed${step.error ? `: ${step.error}` : ""}`}
                    {step.step === "synthesizing" && "Synthesizing responses..."}
                  </span>
                </div>
              )
            })}
          </div>
        ) : (
          isStreaming && streamingAgentStep && (
            <div className="flex items-center gap-2 px-2 py-1.5">
              <span className={streamingAgentStep.step === "failed" ? "h-1.5 w-1.5 rounded-full bg-destructive" : "h-1.5 w-1.5 rounded-full bg-primary animate-pulse"} />
              <span className={streamingAgentStep.step === "failed" ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
                {streamingAgentStep.step === "routing" && "Routing query..."}
                {streamingAgentStep.step === "responding" && `${streamingAgentStep.agent_name} is responding...`}
                {streamingAgentStep.step === "selected" && `Selected ${streamingAgentStep.agent_name}`}
                {streamingAgentStep.step === "completed" && `${streamingAgentStep.agent_name} completed`}
                {streamingAgentStep.step === "failed" && `${streamingAgentStep.agent_name} failed${streamingAgentStep.error ? `: ${streamingAgentStep.error}` : ""}`}
                {streamingAgentStep.step === "synthesizing" && "Synthesizing responses..."}
              </span>
            </div>
          )
        )}

        {/* Streaming message */}
        {hasStreamingActivity && (
          <MessageBubble
            message={{
              id: "streaming",
              session_id: "",
              role: "assistant",
              content: streamingContent,
              agent_id: streamingAgentStep?.agent_id || undefined,
              created_at: new Date().toISOString(),
              reasoning: streamingReasoning
                ? [{ type: "thinking", content: streamingReasoning }]
                : undefined,
            }}
            toolCalls={streamingToolCalls}
            toolRound={streamingToolRound}
            kbContext={streamingKBContext}
            terminalOutput={streamingTerminal}
            terminalComplete={streamingTerminalComplete}
            fileTree={streamingFileTree}
            sourceUrls={streamingSourceUrls}
            plan={streamingPlan}
            jsxPreview={streamingJsx}
            jsxComplete={streamingJsxComplete}
            isStreaming
            hitlApprovalEvent={pendingHITLApproval}
            agentHopLog={streamingAgentHopLog}
            threadContinueEvent={pendingThreadContinue}
            onThreadContinueResolved={onThreadContinueResolved}
            toolProposalEvent={pendingToolProposal}
            generatingTool={generatingTool}
            accessToken={accessToken}
            onHITLResolved={onHITLResolved}
            onToolProposalResolved={onToolProposalResolved}
          />
        )}

        {/* Initial loading dots (before any streaming data arrives) */}
        {isStreaming && !hasStreamingActivity && (
          <MessageBubble
            message={{
              id: "loading",
              session_id: "",
              role: "assistant",
              content: "",
              created_at: new Date().toISOString(),
            }}
            isStreaming
          />
        )}

        {/* Scroll anchor */}
        <div ref={bottomRef} className="h-px" />
      </div>

      <div className="sticky bottom-4 flex justify-center pointer-events-none">
        <div className="pointer-events-auto">
          <ScrollButton visible={showScrollButton} onClick={scrollToBottom} />
        </div>
      </div>
    </div>
  )
}
