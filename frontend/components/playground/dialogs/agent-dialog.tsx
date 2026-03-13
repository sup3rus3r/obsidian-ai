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
import type { Agent, ToolDefinition, MCPServer, KnowledgeBase, AgentMemory, AgentVersion, AgentConfigSnapshot, OptimizationRun, EvalSuite, PromptVaultEntry } from "@/types/playground"
import { Loader2, CheckCircle2, Circle, Server, BookOpen, ExternalLink, ShieldAlert, Brain, Trash2, Wrench, Sparkles, History, RotateCcw, ChevronDown, ChevronRight, Zap, CheckCheck, X, Terminal, Play, Square, BookMarked } from "lucide-react"
import { AppRoutes } from "@/app/api/routes"

// ─── Version diff helpers ────────────────────────────────────────────────────

function resolveJsonIds(
  key: keyof AgentConfigSnapshot,
  raw: string,
  tools: ToolDefinition[],
  mcpServers: MCPServer[],
  kbs: KnowledgeBase[],
): string {
  if (!raw) return raw
  let ids: string[]
  try {
    ids = JSON.parse(raw)
    if (!Array.isArray(ids)) return raw
  } catch {
    return raw
  }
  if (key === "tools_json") {
    return ids.map((id) => tools.find((t) => String(t.id) === String(id))?.name ?? id).join(", ") || "(none)"
  }
  if (key === "mcp_servers_json") {
    return ids.map((id) => mcpServers.find((s) => String(s.id) === String(id))?.name ?? id).join(", ") || "(none)"
  }
  if (key === "knowledge_base_ids_json") {
    return ids.map((id) => kbs.find((k) => String(k.id) === String(id))?.name ?? id).join(", ") || "(none)"
  }
  return raw
}

const SNAPSHOT_LABELS: Record<keyof AgentConfigSnapshot, string> = {
  name: "Name",
  description: "Description",
  system_prompt: "System Prompt",
  provider_id: "Provider",
  model_id: "Model",
  tools_json: "Tools",
  mcp_servers_json: "MCP Servers",
  knowledge_base_ids_json: "Knowledge Bases",
  hitl_confirmation_tools_json: "HITL Tools",
  allow_tool_creation: "Allow Tool Creation",
  config_json: "Config",
}

function snapshotDiff(a: AgentConfigSnapshot, b: AgentConfigSnapshot): Array<{ key: string; label: string; before: string; after: string }> {
  const diffs: Array<{ key: string; label: string; before: string; after: string }> = []
  const keys = Object.keys(SNAPSHOT_LABELS) as Array<keyof AgentConfigSnapshot>
  for (const key of keys) {
    const av = a[key] == null ? "" : String(a[key])
    const bv = b[key] == null ? "" : String(b[key])
    if (av !== bv) {
      diffs.push({ key, label: SNAPSHOT_LABELS[key], before: av, after: bv })
    }
  }
  return diffs
}

function VersionDiffModal({
  version,
  prevVersion,
  onClose,
  onRollback,
  rolling,
  tools,
  mcpServers,
  kbs,
}: {
  version: AgentVersion | null
  prevVersion: AgentVersion | null
  onClose: () => void
  onRollback: () => void
  rolling: boolean
  tools: ToolDefinition[]
  mcpServers: MCPServer[]
  kbs: KnowledgeBase[]
}) {
  const diffs = version && prevVersion
    ? snapshotDiff(prevVersion.config_snapshot, version.config_snapshot)
    : []

  const humanize = (key: keyof AgentConfigSnapshot, raw: string) =>
    resolveJsonIds(key, raw, tools, mcpServers, kbs)

  return (
    <Dialog open={!!version} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-4 py-3 border-b border-border shrink-0">
          <DialogTitle className="flex items-center gap-2 text-sm font-medium">
            <History className="h-4 w-4 text-blue-500" />
            {version && <>v{version.version_number}</>}
            {version?.change_summary && (
              <span className="text-xs text-muted-foreground font-normal">— {version.change_summary}</span>
            )}
          </DialogTitle>
          {version && (
            <DialogDescription className="text-xs text-muted-foreground">
              Saved {new Date(version.created_at).toLocaleString()}
            </DialogDescription>
          )}
        </DialogHeader>

        <div className="overflow-y-auto flex-1 p-4 space-y-3">
          {version && diffs.length === 0 && !prevVersion && (
            <div className="space-y-2">
              {(Object.keys(SNAPSHOT_LABELS) as Array<keyof AgentConfigSnapshot>).map((key) => {
                const val = version.config_snapshot[key]
                if (val == null || val === "" || val === false) return null
                const displayVal = humanize(key, String(val))
                return (
                  <div key={key} className="border border-border/40 rounded overflow-hidden">
                    <div className="px-2 py-1.5 bg-muted/30 text-xs font-medium text-muted-foreground">
                      {SNAPSHOT_LABELS[key]}
                    </div>
                    <pre className="px-2 py-1.5 text-xs text-foreground whitespace-pre-wrap break-all font-mono">
                      {displayVal}
                    </pre>
                  </div>
                )
              })}
            </div>
          )}

          {diffs.length === 0 && prevVersion && (
            <p className="text-xs text-muted-foreground italic">No changes detected between this version and the previous one.</p>
          )}

          {diffs.map((diff) => {
            const beforeDisplay = humanize(diff.key as keyof AgentConfigSnapshot, diff.before)
            const afterDisplay = humanize(diff.key as keyof AgentConfigSnapshot, diff.after)
            return (
              <div key={diff.key} className="border border-border/40 rounded overflow-hidden">
                <div className="px-2 py-1.5 bg-muted/30 text-xs font-medium text-muted-foreground">
                  {diff.label}
                </div>
                <div className="grid grid-cols-2 divide-x divide-border/40 text-[10px] font-mono">
                  <div className="px-2 py-1.5 bg-red-500/5 overflow-x-auto whitespace-pre-wrap break-all text-red-600 dark:text-red-400">
                    <div className="text-[9px] text-muted-foreground mb-1 font-sans">Before</div>
                    {beforeDisplay || <span className="italic text-muted-foreground/60">empty</span>}
                  </div>
                  <div className="px-2 py-1.5 bg-emerald-500/5 overflow-x-auto whitespace-pre-wrap break-all text-emerald-700 dark:text-emerald-400">
                    <div className="text-[9px] text-muted-foreground mb-1 font-sans">After</div>
                    {afterDisplay || <span className="italic text-muted-foreground/60">empty</span>}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <DialogFooter className="px-4 py-3 border-t border-border shrink-0">
          <Button size="sm" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={onRollback}
            disabled={rolling}
            className="gap-1.5"
          >
            {rolling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            Restore this version
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

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
  const [memoryEnabled, setMemoryEnabled] = useState(true)
  const [sandboxEnabled, setSandboxEnabled] = useState(false)
  const [sandboxRunning, setSandboxRunning] = useState(false)
  const [sandboxLoading, setSandboxLoading] = useState(false)
  const [availableTools, setAvailableTools] = useState<ToolDefinition[]>([])
  const [availableMCPServers, setAvailableMCPServers] = useState<MCPServer[]>([])
  const [availableKBs, setAvailableKBs] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [memories, setMemories] = useState<AgentMemory[]>([])
  const [clearingMemories, setClearingMemories] = useState(false)
  const [versions, setVersions] = useState<AgentVersion[]>([])
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [loadingVersions, setLoadingVersions] = useState(false)
  const [diffVersion, setDiffVersion] = useState<AgentVersion | null>(null)
  const [rollingBack, setRollingBack] = useState(false)
  // Optimizer state
  const [optimizerOpen, setOptimizerOpen] = useState(false)
  const [optimizationRuns, setOptimizationRuns] = useState<OptimizationRun[]>([])
  const [loadingOptRuns, setLoadingOptRuns] = useState(false)
  const [activeOptRun, setActiveOptRun] = useState<OptimizationRun | null>(null)
  const [triggeringOpt, setTriggeringOpt] = useState(false)
  const [acceptingOpt, setAcceptingOpt] = useState(false)
  const [rejectingOpt, setRejectingOpt] = useState(false)
  const [optPollTimer, setOptPollTimer] = useState<ReturnType<typeof setInterval> | null>(null)
  const [evalSuites, setEvalSuites] = useState<EvalSuite[]>([])
  const [selectedEvalSuiteId, setSelectedEvalSuiteId] = useState<string>("none")
  // Prompt vault state
  const [promptVaultId, setPromptVaultId] = useState<string | null>(null)
  const [vaultPickerOpen, setVaultPickerOpen] = useState(false)
  const [vaultEntries, setVaultEntries] = useState<PromptVaultEntry[]>([])
  const [loadingVault, setLoadingVault] = useState(false)
  // Optimizer vault actions state
  const [saveToVaultOpen, setSaveToVaultOpen] = useState(false)
  const [updateVaultOpen, setUpdateVaultOpen] = useState(false)
  const [vaultSaveName, setVaultSaveName] = useState("")
  const [vaultSaveDesc, setVaultSaveDesc] = useState("")
  const [savingToVault, setSavingToVault] = useState(false)
  const [optVaultEntries, setOptVaultEntries] = useState<PromptVaultEntry[]>([])
  const [selectedOptVaultId, setSelectedOptVaultId] = useState<string>("")
  const [updatingVault, setUpdatingVault] = useState(false)

  useEffect(() => {
    if (!open) return
    // Load available tools, MCP servers, and knowledge bases
    apiClient.listTools().then(setAvailableTools).catch(() => {})
    apiClient.listMCPServers().then(setAvailableMCPServers).catch(() => {})
    apiClient.listKnowledgeBases().then(setAvailableKBs).catch(() => {})

    // Load eval suites for optimizer selector
    apiClient.listEvalSuites().then(setEvalSuites).catch(() => {})

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
      setMemoryEnabled(agent.memory_enabled ?? true)
      setSandboxEnabled(agent.sandbox_enabled ?? false)
      setSandboxRunning(agent.sandbox_container_id != null && agent.sandbox_enabled === true)
      setPromptVaultId(agent.prompt_vault_id ?? null)
      apiClient.listAgentMemories(agent.id).then(setMemories).catch(() => {})
      setVersions([])
      setVersionsOpen(false)
      setDiffVersion(null)
      // Reset optimizer state
      setOptimizerOpen(false)
      setOptimizationRuns([])
      setActiveOptRun(null)
      setSelectedEvalSuiteId("none")
    } else {
      resetForm()
      setMemories([])
      setVersions([])
      setVersionsOpen(false)
      setDiffVersion(null)
      setOptimizerOpen(false)
      setOptimizationRuns([])
      setActiveOptRun(null)
      setSandboxEnabled(false)
      setSandboxRunning(false)
      setPromptVaultId(null)
    }
    return () => {
      if (optPollTimer) clearInterval(optPollTimer)
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
          prompt_vault_id: promptVaultId ?? undefined,
          provider_id: providerId || undefined,
          model_id: modelId || undefined,
          tools: selectedTools,
          mcp_server_ids: selectedMCPServers,
          knowledge_base_ids: selectedKBs,
          hitl_confirmation_tools: hitlTools.length > 0 ? hitlTools : undefined,
          allow_tool_creation: allowToolCreation,
          memory_enabled: memoryEnabled,
          sandbox_enabled: sandboxEnabled,
        })
        setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
        onSaved?.(updated)
      } else {
        const newAgent = await apiClient.createAgent({
          name,
          description: description || undefined,
          system_prompt: systemPrompt || undefined,
          prompt_vault_id: promptVaultId ?? undefined,
          provider_id: providerId || undefined,
          model_id: modelId || undefined,
          tools: selectedTools.length > 0 ? selectedTools : undefined,
          mcp_server_ids: selectedMCPServers.length > 0 ? selectedMCPServers : undefined,
          knowledge_base_ids: selectedKBs.length > 0 ? selectedKBs : undefined,
          hitl_confirmation_tools: hitlTools.length > 0 ? hitlTools : undefined,
          allow_tool_creation: allowToolCreation,
          memory_enabled: memoryEnabled,
          sandbox_enabled: sandboxEnabled,
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

  const handleSandboxToggle = async () => {
    if (!isEditing || !agent) return
    setSandboxLoading(true)
    try {
      if (sandboxRunning) {
        await apiClient.stopAgentSandbox(agent.id)
        setSandboxRunning(false)
        const updated = { ...agent, sandbox_enabled: sandboxEnabled, sandbox_container_id: null, sandbox_host_port: null }
        setAgents(agents.map((a) => (a.id === agent.id ? updated : a)))
      } else {
        const status = await apiClient.startAgentSandbox(agent.id)
        setSandboxRunning(status.status === "running")
        const updated = { ...agent, sandbox_enabled: true, sandbox_container_id: status.container_id ?? null, sandbox_host_port: status.host_port ?? null }
        setAgents(agents.map((a) => (a.id === agent.id ? updated : a)))
      }
    } catch (err: any) {
      console.error("Sandbox toggle failed:", err)
    } finally {
      setSandboxLoading(false)
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
    setMemoryEnabled(true)
    setError("")
    setMemories([])
    setVersions([])
    setVersionsOpen(false)
    setDiffVersion(null)
  }

  const handleToggleVersions = async () => {
    if (!agent) return
    if (!versionsOpen && versions.length === 0) {
      setLoadingVersions(true)
      try {
        const list = await apiClient.listAgentVersions(agent.id)
        setVersions(list)
      } catch {
        // ignore
      } finally {
        setLoadingVersions(false)
      }
    }
    setVersionsOpen((v) => !v)
  }

  const handleDeleteVersion = async (versionId: string) => {
    if (!agent) return
    setVersions((prev) => prev.filter((v) => String(v.id) !== versionId))
    try {
      await apiClient.deleteAgentVersion(agent.id, versionId)
    } catch {
      const list = await apiClient.listAgentVersions(agent.id).catch(() => [])
      setVersions(list)
    }
  }

  const handleRollback = async () => {
    if (!agent || !diffVersion) return
    setRollingBack(true)
    try {
      await apiClient.rollbackAgentVersion(agent.id, String(diffVersion.id))
      // Reload agent to get fresh config
      const updated = await apiClient.getAgent(agent.id)
      setAgents(agents.map((a) => (a.id === updated.id ? updated : a)))
      onSaved?.(updated)
      setDiffVersion(null)
      onOpenChange(false)
    } catch {
      // ignore
    } finally {
      setRollingBack(false)
    }
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

  // ── Optimizer handlers ──────────────────────────────────────────────────────

  const _startOptPoll = (runId: string) => {
    const timer = setInterval(async () => {
      try {
        const updated = await apiClient.getOptimizationRun(runId)
        setActiveOptRun(updated)
        setOptimizationRuns((prev) =>
          prev.map((r) => (String(r.id) === String(updated.id) ? updated : r))
        )
        const terminal = ["awaiting_review", "accepted", "rejected", "failed"]
        if (terminal.includes(updated.status)) {
          clearInterval(timer)
          setOptPollTimer(null)
        }
      } catch {
        clearInterval(timer)
        setOptPollTimer(null)
      }
    }, 3000)
    setOptPollTimer(timer)
  }

  const handleToggleOptimizer = async () => {
    if (!agent) return
    if (!optimizerOpen && optimizationRuns.length === 0) {
      setLoadingOptRuns(true)
      try {
        const runs = await apiClient.listOptimizationRuns(String(agent.id))
        setOptimizationRuns(runs)
        if (runs.length > 0) setActiveOptRun(runs[0])
      } catch {
        // ignore
      } finally {
        setLoadingOptRuns(false)
      }
    }
    setOptimizerOpen((v) => !v)
  }

  const handleTriggerOptimization = async () => {
    if (!agent) return
    setTriggeringOpt(true)
    try {
      const run = await apiClient.triggerOptimization({
        agent_id: String(agent.id),
        eval_suite_id: selectedEvalSuiteId && selectedEvalSuiteId !== "none" ? selectedEvalSuiteId : undefined,
        min_traces: 5,
        max_traces: 50,
      })
      setOptimizationRuns((prev) => [run, ...prev])
      setActiveOptRun(run)
      _startOptPoll(String(run.id))
    } catch {
      // ignore
    } finally {
      setTriggeringOpt(false)
    }
  }

  const handleAcceptOptimization = async () => {
    if (!activeOptRun) return
    setAcceptingOpt(true)
    try {
      const updated = await apiClient.acceptOptimizationRun(String(activeOptRun.id))
      setActiveOptRun(updated)
      setOptimizationRuns((prev) =>
        prev.map((r) => (String(r.id) === String(updated.id) ? updated : r))
      )
      // Reload agent to reflect the new prompt
      if (agent) {
        const refreshed = await apiClient.getAgent(agent.id)
        setAgents(agents.map((a) => (a.id === refreshed.id ? refreshed : a)))
        onSaved?.(refreshed)
        setSystemPrompt(refreshed.system_prompt || "")
      }
    } catch {
      // ignore
    } finally {
      setAcceptingOpt(false)
    }
  }

  const handleRejectOptimization = async () => {
    if (!activeOptRun) return
    setRejectingOpt(true)
    try {
      const updated = await apiClient.rejectOptimizationRun(String(activeOptRun.id), {})
      setActiveOptRun(updated)
      setOptimizationRuns((prev) =>
        prev.map((r) => (String(r.id) === String(updated.id) ? updated : r))
      )
    } catch {
      // ignore
    } finally {
      setRejectingOpt(false)
    }
  }

  const handleSaveToVault = async () => {
    if (!activeOptRun || !vaultSaveName.trim()) return
    setSavingToVault(true)
    try {
      const res = await fetch(AppRoutes.OptimizerSaveToVault(String(activeOptRun.id)), {
        method: "POST",
        headers: { ...apiClient.getAuthHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ name: vaultSaveName.trim(), description: vaultSaveDesc.trim() || null }),
      })
      if (!res.ok) throw new Error("Failed to save")
      setSaveToVaultOpen(false)
      setVaultSaveName("")
      setVaultSaveDesc("")
    } catch { /* ignore */ } finally {
      setSavingToVault(false)
    }
  }

  const handleUpdateVault = async () => {
    if (!activeOptRun || !selectedOptVaultId) return
    setUpdatingVault(true)
    try {
      const res = await fetch(AppRoutes.OptimizerUpdateVault(String(activeOptRun.id)), {
        method: "POST",
        headers: { ...apiClient.getAuthHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ vault_id: selectedOptVaultId }),
      })
      if (!res.ok) throw new Error("Failed to update")
      setUpdateVaultOpen(false)
      setSelectedOptVaultId("")
    } catch { /* ignore */ } finally {
      setUpdatingVault(false)
    }
  }

  const openUpdateVaultDialog = async () => {
    try {
      const res = await fetch(AppRoutes.ListPrompts(), {
        headers: apiClient.getAuthHeaders(),
      })
      if (res.ok) {
        const data = await res.json()
        setOptVaultEntries(data.prompts || [])
        // pre-select if agent has a vault source
        if (promptVaultId) setSelectedOptVaultId(promptVaultId)
      }
    } catch {}
    setUpdateVaultOpen(true)
  }

  const handleDeleteOptRun = async (runId: string) => {
    setOptimizationRuns((prev) => prev.filter((r) => String(r.id) !== runId))
    if (activeOptRun && String(activeOptRun.id) === runId) setActiveOptRun(null)
    try {
      await apiClient.deleteOptimizationRun(runId)
    } catch {
      // ignore
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
            <div className="flex items-center justify-between">
              <Label htmlFor="system-prompt">System Prompt</Label>
              <button
                type="button"
                className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                onClick={async () => {
                  setLoadingVault(true)
                  try {
                    const res = await fetch(AppRoutes.ListPrompts(), {
                      headers: apiClient.getAuthHeaders(),
                    })
                    if (res.ok) {
                      const data = await res.json()
                      setVaultEntries(data.prompts || [])
                    }
                  } catch {}
                  setLoadingVault(false)
                  setVaultPickerOpen(true)
                }}
              >
                {loadingVault
                  ? <Loader2 className="h-3 w-3 animate-spin" />
                  : <BookMarked className="h-3 w-3" />}
                Load from vault
              </button>
            </div>
            {promptVaultId && (
              <p className="text-xs text-muted-foreground flex items-center gap-1">
                <BookMarked className="h-3 w-3" />
                Loaded from vault
                <button
                  type="button"
                  className="ml-1 underline hover:no-underline"
                  onClick={() => setPromptVaultId(null)}
                >
                  detach
                </button>
              </p>
            )}
            <Textarea
              id="system-prompt"
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a helpful AI assistant..."
              rows={5}
              className="resize-none"
            />
          </div>

          {/* Vault Picker Dialog */}
          <Dialog open={vaultPickerOpen} onOpenChange={setVaultPickerOpen}>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>Load from Prompt Vault</DialogTitle>
                <DialogDescription>
                  Select a prompt to load into the system prompt field.
                </DialogDescription>
              </DialogHeader>
              {vaultEntries.length === 0 ? (
                <p className="text-sm text-muted-foreground py-4 text-center">
                  No prompts in your vault yet.
                </p>
              ) : (
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {vaultEntries.map((entry) => (
                    <button
                      key={entry.id}
                      type="button"
                      className="w-full text-left p-3 border rounded-md hover:border-primary/50 hover:bg-muted/30 transition-colors"
                      onClick={() => {
                        setSystemPrompt(entry.content)
                        setPromptVaultId(entry.id)
                        setVaultPickerOpen(false)
                      }}
                    >
                      <p className="text-sm font-medium">{entry.name}</p>
                      {entry.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">{entry.description}</p>
                      )}
                      <p className="text-xs text-muted-foreground/60 mt-1 line-clamp-2 font-mono">
                        {entry.content}
                      </p>
                    </button>
                  ))}
                </div>
              )}
              <DialogFooter>
                <Button variant="outline" onClick={() => setVaultPickerOpen(false)}>Cancel</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

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

          {/* Docker Sandbox Section */}
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5">
              <Terminal className="h-3.5 w-3.5 text-emerald-500" />
              Docker Sandbox
            </Label>
            <p className="text-xs text-muted-foreground -mt-1">
              Spin up an isolated Docker container for this agent. Injects file and shell tools (bash, read, write, ls, glob, grep, delete) into every conversation.
            </p>
            <button
              type="button"
              onClick={() => setSandboxEnabled((v) => !v)}
              className="w-full flex items-center gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left border border-border"
            >
              {sandboxEnabled ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
              ) : (
                <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
              )}
              <span className={sandboxEnabled ? "text-emerald-600 dark:text-emerald-400 font-medium" : "text-muted-foreground"}>
                {sandboxEnabled ? "Enabled — sandbox tools will be injected" : "Disabled"}
              </span>
            </button>
            {isEditing && sandboxEnabled && (
              <div className="flex items-center gap-2 mt-1">
                <div className={`h-2 w-2 rounded-full shrink-0 ${sandboxRunning ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground/40"}`} />
                <span className="text-xs text-muted-foreground flex-1">
                  {sandboxRunning ? "Container running" : "Container stopped"}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleSandboxToggle}
                  disabled={sandboxLoading}
                  className="h-6 px-2 text-xs gap-1"
                >
                  {sandboxLoading ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : sandboxRunning ? (
                    <><Square className="h-3 w-3" /> Stop</>
                  ) : (
                    <><Play className="h-3 w-3" /> Start</>
                  )}
                </Button>
              </div>
            )}
          </div>

          {/* Version History Section (edit mode only) */}
          {isEditing && (
            <div className="grid gap-2">
              <button
                type="button"
                onClick={handleToggleVersions}
                className="flex items-center gap-1.5 text-sm font-medium w-full text-left"
              >
                {versionsOpen ? (
                  <ChevronDown className="h-3.5 w-3.5 text-blue-500" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 text-blue-500" />
                )}
                <History className="h-3.5 w-3.5 text-blue-500" />
                Version History
                {versions.length > 0 && (
                  <span className="ml-1 text-xs bg-blue-500/10 text-blue-500 px-1.5 py-0.5 rounded-full font-normal">
                    {versions.length}
                  </span>
                )}
                {loadingVersions && <Loader2 className="h-3 w-3 animate-spin ml-1 text-muted-foreground" />}
              </button>
              {versionsOpen && (
                <>
                  <p className="text-xs text-muted-foreground -mt-1">
                    Snapshots saved automatically before each update. Click a version to inspect or restore it.
                  </p>
                  {versions.length === 0 ? (
                    <p className="text-xs text-muted-foreground italic">No versions saved yet. Edit and save the agent to create the first snapshot.</p>
                  ) : (
                    <div className="space-y-1 max-h-52 overflow-y-auto rounded-md border border-border p-2">
                      {versions.map((ver, idx) => (
                        <div
                          key={ver.id}
                          className="flex items-center gap-2 p-2 rounded text-xs hover:bg-muted/40 group cursor-pointer"
                          onClick={() => setDiffVersion(ver)}
                        >
                          <span className="shrink-0 font-mono text-blue-500 font-semibold w-8">v{ver.version_number}</span>
                          <div className="flex-1 min-w-0">
                            <div className="truncate text-muted-foreground">
                              {ver.change_summary || "No summary"}
                            </div>
                            <div className="text-[10px] text-muted-foreground/60 mt-0.5">
                              {new Date(ver.created_at).toLocaleString()}
                            </div>
                          </div>
                          {idx === 0 && (
                            <span className="shrink-0 text-[10px] bg-blue-500/10 text-blue-500 px-1.5 py-0.5 rounded font-medium">latest</span>
                          )}
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleDeleteVersion(String(ver.id)) }}
                            className="shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all"
                            aria-label="Delete version"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

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
                <div className="flex items-center gap-2">
                  {memories.length > 0 && memoryEnabled && (
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
                  <button
                    type="button"
                    onClick={() => setMemoryEnabled((v) => !v)}
                    className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${
                      memoryEnabled
                        ? "bg-violet-500/10 text-violet-600 dark:text-violet-400 border-violet-500/30 hover:bg-violet-500/20"
                        : "bg-muted text-muted-foreground border-border hover:bg-muted/80"
                    }`}
                  >
                    {memoryEnabled ? "On" : "Off"}
                  </button>
                </div>
              </div>
              <p className="text-xs text-muted-foreground -mt-1">
                Facts distilled automatically from past conversations. Injected into every session with this agent.
              </p>
              {!memoryEnabled ? (
                <p className="text-xs text-muted-foreground italic">
                  Memory is disabled. The agent will not retain or use facts from past conversations.
                </p>
              ) : memories.length === 0 ? (
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

          {/* ── Prompt Auto-Optimizer Section (edit mode only) ── */}
          {isEditing && (
            <div className="grid gap-2">
              <button
                type="button"
                onClick={handleToggleOptimizer}
                className="flex items-center gap-2 text-sm font-medium text-left hover:text-foreground transition-colors text-muted-foreground"
              >
                {optimizerOpen ? (
                  <ChevronDown className="h-3.5 w-3.5 text-amber-500" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 text-amber-500" />
                )}
                <Zap className="h-3.5 w-3.5 text-amber-500" />
                Prompt Optimizer
                {optimizationRuns.some((r) => r.status === "awaiting_review") && (
                  <span className="ml-1 text-xs bg-amber-500/10 text-amber-500 px-1.5 py-0.5 rounded-full font-normal">
                    review ready
                  </span>
                )}
                {loadingOptRuns && <Loader2 className="h-3 w-3 animate-spin ml-1 text-muted-foreground" />}
              </button>

              {optimizerOpen && (
                <div className="space-y-3">
                  <p className="text-xs text-muted-foreground -mt-1">
                    Analyzes recent conversation traces to identify failure patterns and proposes an improved system prompt.
                  </p>

                  {/* Trigger controls */}
                  <div className="flex items-center gap-2">
                    <Select
                      value={selectedEvalSuiteId}
                      onValueChange={setSelectedEvalSuiteId}
                    >
                      <SelectTrigger className="h-8 text-xs flex-1">
                        <SelectValue placeholder="Eval suite (optional)" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">None — skip eval validation</SelectItem>
                        {evalSuites.map((s) => (
                          <SelectItem key={String(s.id)} value={String(s.id)}>
                            {s.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={handleTriggerOptimization}
                      disabled={triggeringOpt}
                      className="h-8 text-xs gap-1.5 border-amber-500/30 text-amber-600 hover:bg-amber-500/10"
                    >
                      {triggeringOpt ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Zap className="h-3 w-3" />
                      )}
                      Run optimizer
                    </Button>
                  </div>

                  {/* Active run status + diff view */}
                  {activeOptRun && (
                    <div className="rounded-md border border-border bg-muted/20 p-3 space-y-3">
                      {/* Status header */}
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                            activeOptRun.status === "awaiting_review"
                              ? "bg-amber-500/10 text-amber-600"
                              : activeOptRun.status === "accepted"
                              ? "bg-emerald-500/10 text-emerald-600"
                              : activeOptRun.status === "rejected"
                              ? "bg-rose-500/10 text-rose-600"
                              : activeOptRun.status === "failed"
                              ? "bg-destructive/10 text-destructive"
                              : "bg-muted text-muted-foreground"
                          }`}>
                            {activeOptRun.status.replace("_", " ")}
                          </span>
                          {activeOptRun.trace_count > 0 && (
                            <span className="text-xs text-muted-foreground">
                              {activeOptRun.trace_count} traces analyzed
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2">
                          {activeOptRun.baseline_score !== undefined && activeOptRun.proposed_score !== undefined && (
                            <span className="text-xs text-muted-foreground">
                              baseline&nbsp;<strong>{Math.round(activeOptRun.baseline_score * 100)}%</strong>
                              &nbsp;→&nbsp;proposed&nbsp;
                              <strong className={activeOptRun.proposed_score >= activeOptRun.baseline_score ? "text-emerald-600" : "text-rose-600"}>
                                {Math.round(activeOptRun.proposed_score * 100)}%
                              </strong>
                            </span>
                          )}
                          {(["pending", "analyzing", "proposing", "validating"].includes(activeOptRun.status)) && (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />
                          )}
                          <button
                            type="button"
                            onClick={() => handleDeleteOptRun(String(activeOptRun.id))}
                            className="text-muted-foreground hover:text-destructive transition-colors"
                            aria-label="Delete run"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>

                      {/* Rationale */}
                      {activeOptRun.rationale && (
                        <p className="text-xs text-muted-foreground leading-relaxed">
                          <span className="font-medium text-foreground">Rationale: </span>
                          {activeOptRun.rationale}
                        </p>
                      )}

                      {/* Failure patterns */}
                      {activeOptRun.failure_patterns && activeOptRun.failure_patterns.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-xs font-medium">Failure patterns detected:</p>
                          <div className="flex flex-wrap gap-1">
                            {activeOptRun.failure_patterns.map((fp) => (
                              <span
                                key={fp.pattern}
                                title={fp.description}
                                className={`text-[10px] px-1.5 py-0.5 rounded border ${
                                  fp.severity === "high"
                                    ? "border-rose-500/30 bg-rose-500/5 text-rose-600"
                                    : fp.severity === "medium"
                                    ? "border-amber-500/30 bg-amber-500/5 text-amber-600"
                                    : "border-border bg-muted/30 text-muted-foreground"
                                }`}
                              >
                                {fp.pattern} ×{fp.frequency}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Prompt diff */}
                      {activeOptRun.proposed_prompt && activeOptRun.current_prompt && (
                        <div className="grid grid-cols-2 gap-2">
                          <div className="space-y-1">
                            <p className="text-[10px] uppercase tracking-wide text-muted-foreground font-semibold">Current</p>
                            <pre className="text-xs whitespace-pre-wrap font-mono bg-muted/40 rounded p-2 max-h-48 overflow-y-auto leading-relaxed border border-border">
                              {activeOptRun.current_prompt}
                            </pre>
                          </div>
                          <div className="space-y-1">
                            <p className="text-[10px] uppercase tracking-wide text-amber-600 font-semibold">Proposed</p>
                            <pre className="text-xs whitespace-pre-wrap font-mono bg-amber-500/5 rounded p-2 max-h-48 overflow-y-auto leading-relaxed border border-amber-500/20">
                              {activeOptRun.proposed_prompt}
                            </pre>
                          </div>
                        </div>
                      )}

                      {/* Accept / Reject / Vault */}
                      {activeOptRun.status === "awaiting_review" && (
                        <div className="flex flex-wrap items-center gap-2 pt-1">
                          <Button
                            type="button"
                            size="sm"
                            onClick={handleAcceptOptimization}
                            disabled={acceptingOpt || rejectingOpt}
                            className="h-7 text-xs gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white"
                          >
                            {acceptingOpt ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <CheckCheck className="h-3 w-3" />
                            )}
                            Accept & apply
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => { setVaultSaveName(""); setVaultSaveDesc(""); setSaveToVaultOpen(true) }}
                            disabled={acceptingOpt || rejectingOpt}
                            className="h-7 text-xs gap-1.5"
                          >
                            <BookMarked className="h-3 w-3" />
                            Save to vault
                          </Button>
                          {promptVaultId && (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={openUpdateVaultDialog}
                              disabled={acceptingOpt || rejectingOpt}
                              className="h-7 text-xs gap-1.5"
                            >
                              <BookMarked className="h-3 w-3" />
                              Update vault
                            </Button>
                          )}
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={handleRejectOptimization}
                            disabled={acceptingOpt || rejectingOpt}
                            className="h-7 text-xs gap-1.5 border-rose-500/30 text-rose-600 hover:bg-rose-500/10"
                          >
                            {rejectingOpt ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <X className="h-3 w-3" />
                            )}
                            Reject
                          </Button>
                        </div>
                      )}

                      {/* Save to vault dialog */}
                      <Dialog open={saveToVaultOpen} onOpenChange={setSaveToVaultOpen}>
                        <DialogContent className="max-w-sm">
                          <DialogHeader>
                            <DialogTitle>Save to Prompt Vault</DialogTitle>
                            <DialogDescription>
                              Save the proposed prompt as a new vault entry.
                            </DialogDescription>
                          </DialogHeader>
                          <div className="space-y-3">
                            <div className="space-y-1.5">
                              <Label htmlFor="vault-save-name">Name</Label>
                              <Input
                                id="vault-save-name"
                                value={vaultSaveName}
                                onChange={(e) => setVaultSaveName(e.target.value)}
                                placeholder="e.g., Customer Support v2"
                              />
                            </div>
                            <div className="space-y-1.5">
                              <Label htmlFor="vault-save-desc">Description (Optional)</Label>
                              <Input
                                id="vault-save-desc"
                                value={vaultSaveDesc}
                                onChange={(e) => setVaultSaveDesc(e.target.value)}
                                placeholder="Brief description"
                              />
                            </div>
                          </div>
                          <DialogFooter>
                            <Button variant="outline" onClick={() => setSaveToVaultOpen(false)}>Cancel</Button>
                            <Button
                              onClick={handleSaveToVault}
                              disabled={!vaultSaveName.trim() || savingToVault}
                            >
                              {savingToVault && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
                              Save
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>

                      {/* Update vault dialog */}
                      <Dialog open={updateVaultOpen} onOpenChange={setUpdateVaultOpen}>
                        <DialogContent className="max-w-sm">
                          <DialogHeader>
                            <DialogTitle>Update Vault Entry</DialogTitle>
                            <DialogDescription>
                              Overwrite an existing vault entry with the proposed prompt.
                            </DialogDescription>
                          </DialogHeader>
                          <div className="space-y-2 max-h-64 overflow-y-auto">
                            {optVaultEntries.length === 0 ? (
                              <p className="text-sm text-muted-foreground text-center py-4">No vault entries found.</p>
                            ) : optVaultEntries.map((entry) => (
                              <button
                                key={entry.id}
                                type="button"
                                className={`w-full text-left p-3 border rounded-md transition-colors ${
                                  selectedOptVaultId === entry.id
                                    ? "border-primary bg-primary/5"
                                    : "hover:border-primary/50 hover:bg-muted/30"
                                }`}
                                onClick={() => setSelectedOptVaultId(entry.id)}
                              >
                                <p className="text-sm font-medium">{entry.name}</p>
                                {entry.description && (
                                  <p className="text-xs text-muted-foreground mt-0.5">{entry.description}</p>
                                )}
                              </button>
                            ))}
                          </div>
                          <DialogFooter>
                            <Button variant="outline" onClick={() => setUpdateVaultOpen(false)}>Cancel</Button>
                            <Button
                              onClick={handleUpdateVault}
                              disabled={!selectedOptVaultId || updatingVault}
                            >
                              {updatingVault && <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />}
                              Update
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>

                      {/* Error message */}
                      {activeOptRun.status === "failed" && activeOptRun.error_message && (
                        <p className="text-xs text-destructive">{activeOptRun.error_message}</p>
                      )}
                    </div>
                  )}

                  {/* Past optimization runs list */}
                  {optimizationRuns.length > 1 && (
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">Past runs</p>
                      <div className="space-y-0.5 max-h-36 overflow-y-auto">
                        {optimizationRuns.slice(1).map((run) => (
                          <div
                            key={String(run.id)}
                            className={`flex items-center justify-between px-2 py-1.5 rounded text-xs group cursor-pointer hover:bg-muted/40 ${
                              activeOptRun && String(activeOptRun.id) === String(run.id) ? "bg-muted/60" : ""
                            }`}
                            onClick={() => setActiveOptRun(run)}
                          >
                            <div className="flex items-center gap-2 min-w-0">
                              <span className={`shrink-0 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                                run.status === "awaiting_review"
                                  ? "bg-amber-500/10 text-amber-600"
                                  : run.status === "accepted"
                                  ? "bg-emerald-500/10 text-emerald-600"
                                  : run.status === "rejected"
                                  ? "bg-rose-500/10 text-rose-600"
                                  : run.status === "failed"
                                  ? "bg-destructive/10 text-destructive"
                                  : "bg-muted text-muted-foreground"
                              }`}>
                                {run.status.replace("_", " ")}
                              </span>
                              <span className="text-muted-foreground truncate">
                                {new Date(run.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                              </span>
                              {run.trace_count > 0 && (
                                <span className="text-muted-foreground shrink-0">{run.trace_count} traces</span>
                              )}
                            </div>
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handleDeleteOptRun(String(run.id)) }}
                              className="shrink-0 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-all ml-2"
                              aria-label="Delete run"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
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

      {diffVersion && (
        <VersionDiffModal
          version={diffVersion}
          prevVersion={versions[versions.indexOf(diffVersion) + 1] ?? null}
          onClose={() => setDiffVersion(null)}
          onRollback={handleRollback}
          rolling={rollingBack}
          tools={availableTools}
          mcpServers={availableMCPServers}
          kbs={availableKBs}
        />
      )}
    </Dialog>
  )
}
