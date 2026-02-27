"use client"

import { useEffect } from "react"
import { usePlaygroundStore } from "@/stores/playground-store"
import { useSession } from "next-auth/react"
import { MessageList } from "./message-list"
import { ChatInput } from "./chat-input"
import { ChatSuggestions } from "./chat-suggestions"
import { streamChat } from "@/lib/stream"
import { createSession } from "@/app/api/playground"
import { AppRoutes } from "@/app/api/routes"
import { Bot } from "lucide-react"
import { toast } from "sonner"
import type { Message, FileAttachment, ArtifactType } from "@/types/playground"
import type { FileUIPart } from "ai"

export function ChatArea() {
  const { data: authSession } = useSession()
  const mode = usePlaygroundStore((s) => s.mode)
  const selectedAgentId = usePlaygroundStore((s) => s.selectedAgentId)
  const selectedTeamId = usePlaygroundStore((s) => s.selectedTeamId)
  const selectedSessionId = usePlaygroundStore((s) => s.selectedSessionId)
  const setSelectedSession = usePlaygroundStore((s) => s.setSelectedSession)
  const agents = usePlaygroundStore((s) => s.agents)
  const messages = usePlaygroundStore((s) => s.messages)
  const addMessage = usePlaygroundStore((s) => s.addMessage)
  const isStreaming = usePlaygroundStore((s) => s.isStreaming)
  const setIsStreaming = usePlaygroundStore((s) => s.setIsStreaming)
  const streamingContent = usePlaygroundStore((s) => s.streamingContent)
  const setStreamingContent = usePlaygroundStore((s) => s.setStreamingContent)
  const appendStreamingContent = usePlaygroundStore((s) => s.appendStreamingContent)
  const streamingReasoning = usePlaygroundStore((s) => s.streamingReasoning)
  const setStreamingReasoning = usePlaygroundStore((s) => s.setStreamingReasoning)
  const appendStreamingReasoning = usePlaygroundStore((s) => s.appendStreamingReasoning)
  const streamingToolCalls = usePlaygroundStore((s) => s.streamingToolCalls)
  const setStreamingToolCalls = usePlaygroundStore((s) => s.setStreamingToolCalls)
  const upsertStreamingToolCall = usePlaygroundStore((s) => s.upsertStreamingToolCall)
  const streamingAgentStep = usePlaygroundStore((s) => s.streamingAgentStep)
  const setStreamingAgentStep = usePlaygroundStore((s) => s.setStreamingAgentStep)
  const streamingToolRound = usePlaygroundStore((s) => s.streamingToolRound)
  const setStreamingToolRound = usePlaygroundStore((s) => s.setStreamingToolRound)
  const streamingKBContext = usePlaygroundStore((s) => s.streamingKBContext)
  const setStreamingKBContext = usePlaygroundStore((s) => s.setStreamingKBContext)
  const setAbortController = usePlaygroundStore((s) => s.setAbortController)
  const abortController = usePlaygroundStore((s) => s.abortController)
  const updateSessionTokensInList = usePlaygroundStore((s) => s.updateSessionTokensInList)

  // AI Elements streaming state
  const streamingTerminal = usePlaygroundStore((s) => s.streamingTerminal)
  const streamingTerminalComplete = usePlaygroundStore((s) => s.streamingTerminalComplete)
  const streamingFileTree = usePlaygroundStore((s) => s.streamingFileTree)
  const streamingSourceUrls = usePlaygroundStore((s) => s.streamingSourceUrls)
  const streamingPlan = usePlaygroundStore((s) => s.streamingPlan)
  const streamingJsx = usePlaygroundStore((s) => s.streamingJsx)
  const streamingJsxComplete = usePlaygroundStore((s) => s.streamingJsxComplete)
  const appendStreamingTerminal = usePlaygroundStore((s) => s.appendStreamingTerminal)
  const setStreamingTerminalComplete = usePlaygroundStore((s) => s.setStreamingTerminalComplete)
  const setStreamingFileTree = usePlaygroundStore((s) => s.setStreamingFileTree)
  const addStreamingSourceUrl = usePlaygroundStore((s) => s.addStreamingSourceUrl)
  const setStreamingPlan = usePlaygroundStore((s) => s.setStreamingPlan)
  const appendStreamingPlanStep = usePlaygroundStore((s) => s.appendStreamingPlanStep)
  const completePlan = usePlaygroundStore((s) => s.completePlan)
  const setStreamingJsx = usePlaygroundStore((s) => s.setStreamingJsx)
  const setSessions = usePlaygroundStore((s) => s.setSessions)
  const sessions = usePlaygroundStore((s) => s.sessions)
  const teams = usePlaygroundStore((s) => s.teams)
  const pendingHITLApproval = usePlaygroundStore((s) => s.pendingHITLApproval)
  const setHITLApprovalRequired = usePlaygroundStore((s) => s.setHITLApprovalRequired)
  const pendingToolProposal = usePlaygroundStore((s) => s.pendingToolProposal)
  const setPendingToolProposal = usePlaygroundStore((s) => s.setPendingToolProposal)
  const generatingTool = usePlaygroundStore((s) => s.generatingTool)
  const setGeneratingTool = usePlaygroundStore((s) => s.setGeneratingTool)
  const upsertArtifact = usePlaygroundStore((s) => s.upsertArtifact)
  const setStreamingArtifact = usePlaygroundStore((s) => s.setStreamingArtifact)

  const entityId = mode === "agent" ? selectedAgentId : selectedTeamId
  const hasEntity = !!entityId

  // On session load, check for pending HITL approvals + tool proposals (reconnect support)
  useEffect(() => {
    if (!selectedSessionId || !authSession?.accessToken) return
    setHITLApprovalRequired(null)
    setPendingToolProposal(null)
    fetch(AppRoutes.HITLPending(selectedSessionId), {
      headers: { Authorization: `Bearer ${authSession.accessToken}` },
    })
      .then((r) => r.json())
      .then((data) => {
        if (data?.approvals?.length > 0) {
          setHITLApprovalRequired(data.approvals[0])
        }
      })
      .catch(() => {})
    fetch(AppRoutes.ToolProposalPending(selectedSessionId), {
      headers: { Authorization: `Bearer ${authSession.accessToken}` },
    })
      .then((r) => r.json())
      .then((data) => {
        if (data?.proposals?.length > 0) {
          setPendingToolProposal(data.proposals[0])
        }
      })
      .catch(() => {})
  }, [selectedSessionId, authSession?.accessToken])

  const sendMessage = async (content: string, files?: FileUIPart[]) => {
    if (!authSession?.accessToken || !entityId || isStreaming) return

    let sessionId = selectedSessionId

    // Create session if needed
    if (!sessionId) {
      try {
        const newSession = await createSession(authSession.accessToken, {
          entity_type: mode,
          entity_id: entityId,
          title: content.slice(0, 50),
        })
        sessionId = newSession.id
        setSelectedSession(sessionId)
        setSessions([newSession, ...sessions])
      } catch (err) {
        console.error("Failed to create session:", err)
        return
      }
    }

    // Convert FileUIPart[] to FileAttachment[] for the message + request
    const attachments: FileAttachment[] | undefined = files?.map((f) => ({
      filename: f.filename || "file",
      media_type: f.mediaType,
      file_type: f.mediaType.startsWith("image/") ? "image" as const : "document" as const,
      data: f.url,
    }))

    // Add user message
    const userMessage: Message = {
      id: `temp-${Date.now()}`,
      session_id: sessionId,
      role: "user",
      content,
      attachments,
      created_at: new Date().toISOString(),
    }
    addMessage(userMessage)

    // Start streaming
    const controller = new AbortController()
    setAbortController(controller)
    setIsStreaming(true)
    setStreamingContent("")
    setStreamingReasoning("")
    setStreamingToolCalls([])
    setStreamingAgentStep(null)
    setStreamingToolRound(null)
    setStreamingKBContext([])
    setStreamingTerminalComplete(false)
    setStreamingFileTree(null)
    setStreamingPlan(null)
    setStreamingJsx("", false)
    usePlaygroundStore.setState({ streamingTerminal: "", streamingSourceUrls: [] })

    // If this is a patch edit, pre-populate streamingArtifact with the existing artifact
    // so the panel immediately shows "patching" state with the current content visible
    const editPrefixMatch = content.match(/^\[EDIT ARTIFACT\s+id="([^"]*)"\s+title="([^"]*)"\s+type="([^"]*)"\]/)
    if (editPrefixMatch) {
      const existingArtifact = usePlaygroundStore.getState().artifacts.find((a) => a.id === editPrefixMatch[1])
      if (existingArtifact) {
        setStreamingArtifact({ id: existingArtifact.id, title: existingArtifact.title, type: existingArtifact.type, content: existingArtifact.content })
      } else {
        setStreamingArtifact(null)
      }
    } else {
      setStreamingArtifact(null)
    }

    try {
      await streamChat(
        authSession.accessToken,
        sessionId,
        content,
        (chunk) => appendStreamingContent(chunk),
        (toolCall) => {
          upsertStreamingToolCall(toolCall)
        },
        (reasoning) => appendStreamingReasoning(reasoning.content),
        (message) => {
          // Attach tool calls collected during streaming to the final message
          const currentToolCalls = usePlaygroundStore.getState().streamingToolCalls
          addMessage(currentToolCalls.length > 0 ? { ...message, tool_calls: currentToolCalls } : message)
          setStreamingContent("")
          setStreamingReasoning("")
          setStreamingToolCalls([])
          setStreamingAgentStep(null)
          setStreamingToolRound(null)
          setStreamingKBContext([])
          setHITLApprovalRequired(null)
          setPendingToolProposal(null)
          setGeneratingTool(null)
          setStreamingArtifact(null)
          // Client-side fallback: extract any <artifact> tags from final message content
          // in case the SSE artifact event was missed during streaming
          if (message.content) {
            const ARTIFACT_RE = /<artifact\s+([^>]*)>([\s\S]*?)<\/artifact>/g
            const ATTR_RE = /(\w[\w-]*)\s*=\s*"([^"]*)"/g
            let m: RegExpExecArray | null
            while ((m = ARTIFACT_RE.exec(message.content)) !== null) {
              const attrs: Record<string, string> = {}
              let a: RegExpExecArray | null
              const attrRe = new RegExp(ATTR_RE.source, "g")
              while ((a = attrRe.exec(m[1])) !== null) attrs[a[1]] = a[2]
              if (attrs.id) {
                upsertArtifact({
                  id: attrs.id,
                  title: attrs.title ?? "Artifact",
                  type: (attrs.type ?? "text") as ArtifactType,
                  content: m[2].trim(),
                  sessionId: sessionId!,
                })
              }
            }
          }
        },
        (error) => {
          console.error("Stream error:", error)
          addMessage({
            id: `error-${Date.now()}`,
            session_id: sessionId!,
            role: "assistant",
            content: `Error: ${error}`,
            created_at: new Date().toISOString(),
          })
        },
        (step) => setStreamingAgentStep(step),
        (agentId, agentName, content) => {
          // Collaborate mode: add each non-final agent's response as a completed message
          addMessage({
            id: `collab-${agentId}-${Date.now()}`,
            session_id: sessionId!,
            role: "assistant",
            content,
            agent_id: agentId,
            metadata: { team_mode: "collaborate", intermediate: true, agent_name: agentName },
            created_at: new Date().toISOString(),
          })
        },
        (round) => setStreamingToolRound(round),
        controller.signal,
        attachments,
        (event) => setStreamingKBContext(event.kbs),
        (event) => {
          const names = event.kbs.map((kb) => kb.name).join(", ")
          toast.warning(`Knowledge base not indexed: ${names}`, {
            description: "Add documents to this knowledge base so it can be searched.",
          })
        },
        // AI Elements callbacks
        (content, isComplete) => {
          appendStreamingTerminal(content)
          if (isComplete) setStreamingTerminalComplete(true)
        },
        (nodes) => setStreamingFileTree(nodes),
        (url, title) => addStreamingSourceUrl(url, title),
        (title, description) => setStreamingPlan({ title, description, steps: [], isComplete: false }),
        (step) => appendStreamingPlanStep(step),
        () => completePlan(),
        (jsx, isComplete) => setStreamingJsx(jsx, isComplete),
        (usage) => {
          if (sessionId) {
            updateSessionTokensInList(sessionId, usage.session_total_input, usage.session_total_output)
          }
        },
        (event) => {
          addMessage({
            id: `compaction-${Date.now()}`,
            session_id: sessionId!,
            role: "system",
            content: `__compacted__:${event.messages_summarized}`,
            created_at: new Date().toISOString(),
          })
        },
        (event) => setHITLApprovalRequired(event),
        (event) => { setGeneratingTool(null); setPendingToolProposal(event) },
        (event) => setGeneratingTool(event),
        (event) => {
          if (event.is_complete) {
            upsertArtifact({
              id: event.id,
              title: event.title,
              type: event.type,
              content: event.content,
              sessionId: sessionId!,
            })
            setStreamingArtifact(null)
          } else {
            setStreamingArtifact({ id: event.id, title: event.title, type: event.type, content: event.content })
          }
        },
      )
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        console.error("Chat error:", err)
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      setStreamingAgentStep(null)
      setStreamingToolRound(null)
    }
  }

  const stopStreaming = () => {
    abortController?.abort()
    setIsStreaming(false)
    setStreamingAgentStep(null)
    // Save whatever was streamed so far
    const state = usePlaygroundStore.getState()
    const content = state.streamingContent
    const toolCalls = state.streamingToolCalls
    if (content || toolCalls.length > 0) {
      addMessage({
        id: `stopped-${Date.now()}`,
        session_id: selectedSessionId || "",
        role: "assistant",
        content,
        tool_calls: toolCalls.length > 0 ? toolCalls : undefined,
        created_at: new Date().toISOString(),
      })
      setStreamingContent("")
      setStreamingReasoning("")
      setStreamingToolCalls([])
    }
  }

  if (!hasEntity) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <div className="flex items-center justify-center h-16 w-16 rounded-2xl bg-muted">
          <Bot className="h-8 w-8 text-muted-foreground" />
        </div>
        <div className="text-center space-y-1">
          <h2 className="text-lg font-semibold">Obsidian AI</h2>
          <p className="text-sm text-muted-foreground max-w-md">
            Select an agent from the sidebar to start a conversation, or create a new one.
          </p>
        </div>
      </div>
    )
  }

  const selectedAgent = mode === "agent" ? agents.find((a) => a.id === selectedAgentId) : undefined
  const selectedTeam = mode === "team" ? teams.find((t) => t.id === selectedTeamId) : undefined
  const teamAgents = selectedTeam
    ? agents.filter((a) => selectedTeam.agent_ids.includes(a.id))
    : undefined

  const showSuggestions = hasEntity && messages.length === 0 && !isStreaming && !selectedSessionId

  return (
    <div className="flex flex-col h-full min-h-0">
      {showSuggestions ? (
        <ChatSuggestions
          agent={selectedAgent}
          team={selectedTeam}
          teamAgents={teamAgents}
          mode={mode}
          onSelect={sendMessage}
        />
      ) : (
        <MessageList
          messages={messages}
          streamingContent={streamingContent}
          streamingReasoning={streamingReasoning}
          streamingToolCalls={streamingToolCalls}
          streamingAgentStep={streamingAgentStep}
          streamingToolRound={streamingToolRound}
          streamingKBContext={streamingKBContext}
          isStreaming={isStreaming}
          streamingTerminal={streamingTerminal}
          streamingTerminalComplete={streamingTerminalComplete}
          streamingFileTree={streamingFileTree}
          streamingSourceUrls={streamingSourceUrls}
          streamingPlan={streamingPlan}
          streamingJsx={streamingJsx}
          streamingJsxComplete={streamingJsxComplete}
          pendingHITLApproval={pendingHITLApproval}
          pendingToolProposal={pendingToolProposal}
          generatingTool={generatingTool}
          accessToken={authSession?.accessToken}
          onHITLResolved={() => setHITLApprovalRequired(null)}
          onToolProposalResolved={() => { setPendingToolProposal(null); setGeneratingTool(null) }}
        />
      )}
      <ChatInput
        onSend={sendMessage}
        onStop={stopStreaming}
        isStreaming={isStreaming}
        disabled={!hasEntity}
      />
    </div>
  )
}
