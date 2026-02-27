"use client"

import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import Link from "next/link"
import { apiClient } from "@/lib/api-client"
import { usePlaygroundStore } from "@/stores/playground-store"
import type { Agent, ToolDefinition, MCPServer, KnowledgeBase, AgentMemory } from "@/types/playground"
import { Loader2, CheckCircle2, Circle, Server, BookOpen, ExternalLink, ShieldAlert, Brain, Trash2, Wrench, Sparkles } from "lucide-react"

interface AgentDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agent?: Agent | null
  onSaved?: (agent: Agent) => void
}

export function AgentDialog({ open, onOpenChange, agent, onSaved }: AgentDialogProps) {
  const providers = usePlaygroundStore((s) => s.providers)
  const agents = usePlaygroundStore((s) => s.agents)
  const setAgents = usePlaygroundStore((s) => s.setAgents)
  const setSelectedAgent = usePlaygroundStore((s) => s.setSelectedAgent)

  const isEditing = !!agent

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [systemPrompt, setSystemPrompt] = useState("")
  const [providerId, setProviderId] = useState("")
  const [modelId, setModelId] = useState("")
  const [selectedTools, setSelectedTools] = useState<string[]>([])
  const [selectedMCPServers, setSelectedMCPServers] = useState<string[]>([])
  const [selectedKBs, setSelectedKBs] = useState<string[]>([])
  const [hitlTools, setHitlTools] = useState<string[]>([])
  const [allowToolCreation, setAllowToolCreation] = useState(false)
  const [availableTools, setAvailableTools] = useState<ToolDefinition[]>([])
  const [availableMCPServers, setAvailableMCPServers] = useState<MCPServer[]>([])
  const [availableKBs, setAvailableKBs] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [memories, setMemories] = useState<AgentMemory[]>([])
  const [clearingMemories, setClearingMemories] = useState(false)

  useEffect(() => {
    if (!open) return
    // Load available tools, MCP servers, and knowledge bases
    apiClient.listTools().then(setAvailableTools).catch(() => {})
    apiClient.listMCPServers().then(setAvailableMCPServers).catch(() => {})
    apiClient.listKnowledgeBases().then(setAvailableKBs).catch(() => {})

    if (agent) {
      setName(agent.name)
      setDescription(agent.description || "")
      setSystemPrompt(agent.system_prompt || "")
      setProviderId(agent.provider_id || "")
      setModelId(agent.model_id || "")
      setSelectedTools(agent.tools || [])
      setSelectedMCPServers(agent.mcp_server_ids || [])
      setSelectedKBs(agent.knowledge_base_ids || [])
      setHitlTools(agent.hitl_confirmation_tools || [])
      setAllowToolCreation(agent.allow_tool_creation ?? false)
      apiClient.listAgentMemories(agent.id).then(setMemories).catch(() => {})
    } else {
      resetForm()
      setMemories([])
    }
  }, [open, agent])

  const handleSave = async () => {
    if (!name) return
    setLoading(true)
    setError("")
    try {
      if (isEditing && agent) {
        const updated = await apiClient.updateAgent(agent.id, {
          name,
          description: description || undefined,
          system_prompt: systemPrompt || undefined,
          provider_id: providerId || undefined,
          model_id: modelId || undefined,
          tools: selectedTools,
          mcp_server_ids: selectedMCPServers,
          knowledge_base_ids: selectedKBs,
          hitl_confirmation_tools: hitlTools.length > 0 ? hitlTools : undefined,
          allow_tool_creation: allowToolCreation,
        })
        setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
        onSaved?.(updated)
      } else {
        const newAgent = await apiClient.createAgent({
          name,
          description: description || undefined,
          system_prompt: systemPrompt || undefined,
          provider_id: providerId || undefined,
          model_id: modelId || undefined,
          tools: selectedTools.length > 0 ? selectedTools : undefined,
          mcp_server_ids: selectedMCPServers.length > 0 ? selectedMCPServers : undefined,
          knowledge_base_ids: selectedKBs.length > 0 ? selectedKBs : undefined,
          hitl_confirmation_tools: hitlTools.length > 0 ? hitlTools : undefined,
          allow_tool_creation: allowToolCreation,
        })
        setAgents([...agents, newAgent])
        setSelectedAgent(newAgent.id)
        onSaved?.(newAgent)
      }
      resetForm()
      onOpenChange(false)
    } catch (err: any) {
      console.error("Failed to save agent:", err)
      setError(err?.message || "Failed to save agent")
    } finally {
      setLoading(false)
    }
  }

  const toggleTool = (toolId: string) => {
    setSelectedTools((prev) =>
      prev.includes(toolId)
        ? prev.filter((t) => t !== toolId)
        : [...prev, toolId]
    )
  }

  const toggleMCPServer = (serverId: string) => {
    setSelectedMCPServers((prev) =>
      prev.includes(serverId)
        ? prev.filter((s) => s !== serverId)
        : [...prev, serverId]
    )
  }

  const toggleKB = (kbId: string) => {
    setSelectedKBs((prev) =>
      prev.includes(kbId)
        ? prev.filter((k) => k !== kbId)
        : [...prev, kbId]
    )
  }

  const toggleHitlTool = (toolName: string) => {
    setHitlTools((prev) =>
      prev.includes(toolName)
        ? prev.filter((t) => t !== toolName)
        : [...prev, toolName]
    )
  }

  const resetForm = () => {
    setName("")
    setDescription("")
    setSystemPrompt("")
    setProviderId("")
    setModelId("")
    setSelectedTools([])
    setSelectedMCPServers([])
    setSelectedKBs([])
    setHitlTools([])
    setAllowToolCreation(false)
    setError("")
    setMemories([])
  }

  const handleDeleteMemory = async (memoryId: string) => {
    if (!agent) return
    setMemories((prev) => prev.filter((m) => m.id !== memoryId))
    try {
      await apiClient.deleteAgentMemory(agent.id, memoryId)
    } catch {
      // Refetch on error to restore state
      apiClient.listAgentMemories(agent.id).then(setMemories).catch(() => {})
    }
  }

  const handleClearMemories = async () => {
    if (!agent) return
    setClearingMemories(true)
    try {
      await apiClient.clearAgentMemories(agent.id)
      setMemories([])
    } catch {
      // ignore
    } finally {
      setClearingMemories(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-150 max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Agent" : "Create Agent"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update agent configuration, model, and tools."
              : "Configure a new AI agent with a system prompt and model."}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="agent-name">Name</Label>
            <Input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Assistant"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="agent-desc">Description</Label>
            <Input
              id="agent-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A helpful AI assistant"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="agent-provider">Provider</Label>
            <Select value={providerId} onValueChange={setProviderId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a provider..." />
              </SelectTrigger>
              <SelectContent>
                {providers.length === 0 ? (
                  <SelectItem value="none" disabled>
                    No providers configured
                  </SelectItem>
                ) : (
                  providers.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}
                    </SelectItem>
                  ))
                )}
              </SelectContent>
            </Select>
            {providers.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Add a provider first to connect this agent to an LLM.
              </p>
            )}
          </div>

          <div className="grid gap-2">
            <Label htmlFor="agent-model-id">Model ID</Label>
            <Input
              id="agent-model-id"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              placeholder={
                providers.find((p) => p.id === providerId)?.provider_type === "anthropic"
                  ? "e.g. claude-sonnet-4-6"
                  : providers.find((p) => p.id === providerId)?.provider_type === "google"
                  ? "e.g. gemini-2.0-flash"
                  : providers.find((p) => p.id === providerId)?.provider_type === "ollama"
                  ? "e.g. llama3"
                  : providers.find((p) => p.id === providerId)?.provider_type === "openrouter"
                  ? "e.g. openai/gpt-4o"
                  : "e.g. gpt-4o"
              }
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="system-prompt">System Prompt</Label>
            <Textarea
              id="system-prompt"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a helpful AI assistant..."
              rows={5}
              className="resize-none"
            />
          </div>

          {/* Tools Section */}
          <div className="grid gap-2">
            <Label>Tools</Label>
            {availableTools.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No tools available. Create tools from the playground sidebar to enable them here.
              </p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto rounded-md border border-border p-2">
                {availableTools.map((tool) => {
                  const isEnabled = selectedTools.includes(tool.id)
                  return (
                    <button
                      key={tool.id}
                      type="button"
                      onClick={() => toggleTool(tool.id)}
                      className="w-full flex items-start gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                    >
                      <div className="pt-0.5">
                        {isEnabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">{tool.name}</div>
                        {tool.description && (
                          <div className="text-muted-foreground truncate">
                            {tool.description}
                          </div>
                        )}
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* MCP Servers Section */}
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5">
              <Server className="h-3.5 w-3.5" />
              MCP Servers
            </Label>
            {availableMCPServers.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No MCP servers configured. Add servers from the playground sidebar.
              </p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto rounded-md border border-border p-2">
                {availableMCPServers.map((server) => {
                  const isEnabled = selectedMCPServers.includes(server.id)
                  return (
                    <button
                      key={server.id}
                      type="button"
                      onClick={() => toggleMCPServer(server.id)}
                      className="w-full flex items-start gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                    >
                      <div className="pt-0.5">
                        {isEnabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">{server.name}</div>
                        {server.description && (
                          <div className="text-muted-foreground truncate">
                            {server.description}
                          </div>
                        )}
                        <div className="text-muted-foreground/60 mt-0.5">
                          {server.transport_type}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Knowledge Bases Section */}
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5">
              <BookOpen className="h-3.5 w-3.5" />
              Knowledge Bases
            </Label>
            {availableKBs.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No knowledge bases available.{" "}
                <Link href="/knowledge" className="underline hover:text-foreground inline-flex items-center gap-0.5">
                  Create one
                  <ExternalLink className="h-3 w-3" />
                </Link>{" "}
                to enable RAG for this agent.
              </p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto rounded-md border border-border p-2">
                {availableKBs.map((kb) => {
                  const isEnabled = selectedKBs.includes(kb.id)
                  return (
                    <button
                      key={kb.id}
                      type="button"
                      onClick={() => toggleKB(kb.id)}
                      className="w-full flex items-start gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                    >
                      <div className="pt-0.5">
                        {isEnabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">{kb.name}</div>
                        {kb.description && (
                          <div className="text-muted-foreground truncate">{kb.description}</div>
                        )}
                        <div className="text-muted-foreground/60 mt-0.5">
                          {kb.document_count} document{kb.document_count !== 1 ? "s" : ""}
                          {kb.is_shared ? " · Shared" : ""}
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* HITL Tool Overrides Section */}
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5">
              <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />
              Require Approval For
            </Label>
            <p className="text-xs text-muted-foreground -mt-1">
              Override: these tools will always require human approval before execution, regardless of tool settings.
            </p>
            {availableTools.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No tools available to configure.
              </p>
            ) : (
              <div className="space-y-1 max-h-36 overflow-y-auto rounded-md border border-border p-2">
                {availableTools.map((tool) => {
                  const isOverridden = hitlTools.includes(tool.name)
                  return (
                    <button
                      key={tool.id}
                      type="button"
                      onClick={() => toggleHitlTool(tool.name)}
                      className="w-full flex items-start gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                    >
                      <div className="pt-0.5">
                        {isOverridden ? (
                          <CheckCircle2 className="h-4 w-4 text-amber-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium font-mono">{tool.name}</div>
                        {tool.description && (
                          <div className="text-muted-foreground truncate">{tool.description}</div>
                        )}
                        {tool.requires_confirmation && (
                          <div className="text-amber-500/80 mt-0.5">Already requires approval</div>
                        )}
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Allow Tool Creation Section */}
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5">
              <Wrench className="h-3.5 w-3.5 text-violet-500" />
              <Sparkles className="h-3 w-3 text-violet-400" />
              Allow Tool Creation
            </Label>
            <p className="text-xs text-muted-foreground -mt-1">
              Agent can propose new tools during conversations. You'll review each proposal before it's saved to your toolkit.
            </p>
            <button
              type="button"
              onClick={() => setAllowToolCreation((v) => !v)}
              className="w-full flex items-center gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left border border-border"
            >
              {allowToolCreation ? (
                <CheckCircle2 className="h-4 w-4 text-violet-500 shrink-0" />
              ) : (
                <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
              )}
              <span className={allowToolCreation ? "text-violet-600 dark:text-violet-400 font-medium" : "text-muted-foreground"}>
                {allowToolCreation ? "Enabled — agent can propose new tools" : "Disabled"}
              </span>
            </button>
          </div>

          {/* Long-term Memory Section (edit mode only) */}
          {isEditing && (
            <div className="grid gap-2">
              <div className="flex items-center justify-between">
                <Label className="flex items-center gap-1.5">
                  <Brain className="h-3.5 w-3.5 text-violet-500" />
                  Long-term Memory
                  {memories.length > 0 && (
                    <span className="ml-1 text-xs bg-violet-500/10 text-violet-500 px-1.5 py-0.5 rounded-full font-normal">
                      {memories.length}
                    </span>
                  )}
                </Label>
                {memories.length > 0 && (
                  <button
                    type="button"
                    onClick={handleClearMemories}
                    disabled={clearingMemories}
                    className="text-xs text-muted-foreground hover:text-destructive transition-colors flex items-center gap-1"
                  >
                    {clearingMemories ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Trash2 className="h-3 w-3" />
                    )}
                    Clear all
                  </button>
                )}
              </div>
              <p className="text-xs text-muted-foreground -mt-1">
                Facts distilled automatically from past conversations. Injected into every session with this agent.
              </p>
              {memories.length === 0 ? (
                <p className="text-xs text-muted-foreground italic">
                  No memories yet. Start a new session after finishing a conversation — the agent will reflect and distill key facts automatically.
                </p>
              ) : (
                <div className="space-y-1 max-h-48 overflow-y-auto rounded-md border border-border p-2">
                  {memories.map((mem) => (
                    <div
                      key={mem.id}
                      className="flex items-start gap-2 p-2 rounded text-xs hover:bg-muted/30 group"
                    >
                      <span className={`shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium ${
                        mem.category === "preference"
                          ? "bg-blue-500/10 text-blue-500"
                          : mem.category === "decision"
                          ? "bg-emerald-500/10 text-emerald-500"
                          : mem.category === "correction"
                          ? "bg-amber-500/10 text-amber-500"
                          : "bg-muted text-muted-foreground"
                      }`}>
                        {mem.category}
                      </span>
                      <span className="flex-1 text-foreground leading-relaxed">{mem.value}</span>
                      <button
                        type="button"
                        onClick={() => handleDeleteMemory(mem.id)}
                        className="shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all"
                        aria-label="Delete memory"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={loading || !name}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {isEditing ? "Save Changes" : "Create Agent"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
