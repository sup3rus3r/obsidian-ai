"use client"

import { useState, useEffect } from "react"
import dynamic from "next/dynamic"
import { useTheme } from "next-themes"
import "@uiw/react-md-editor/markdown-editor.css"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useSession } from "next-auth/react"
import { createTeam, updateTeam, addTeamMember, updateTeamMember, removeTeamMember } from "@/app/api/playground"
import { apiClient } from "@/lib/api-client"
import { usePlaygroundStore } from "@/stores/playground-store"
import {
  Loader2, CheckCircle2, Circle, Terminal, Play, Square, Plus, Trash2,
  ChevronDown, ChevronRight, Users2, CheckCheck,
} from "lucide-react"
import type { Team, TeamMember, TeamMemberCreate, ToolDefinition, MCPServer, KnowledgeBase, Skill } from "@/types/playground"

const MDEditor = dynamic(() => import("@uiw/react-md-editor"), { ssr: false })

interface TeamDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  team?: Team | null
}

// A draft member slot in the dialog's local state — matches TeamMember's
// shape but with a client-side tempId for not-yet-saved slots (edit mode
// diffs against the team's original members, create mode posts them all at
// save time), plus an isNew flag so edit-mode save knows whether to POST or
// PATCH/skip.
interface MemberDraft {
  tempId: string
  memberId?: string          // set once this slot has a real TeamMember id (edit mode, already saved)
  agent_id: string
  override_name: string
  override_system_prompt: string
  override_tool_ids: string[] | null
  override_mcp_server_ids: string[] | null
  override_skill_ids: string[] | null
  override_knowledge_base_ids: string[] | null
  can_delegate: boolean
  expanded: boolean
}

function memberToDraft(m: TeamMember): MemberDraft {
  return {
    tempId: m.id,
    memberId: m.id,
    agent_id: m.agent_id,
    override_name: m.override_name ?? "",
    override_system_prompt: m.override_system_prompt ?? "",
    override_tool_ids: m.override_tool_ids ?? null,
    override_mcp_server_ids: m.override_mcp_server_ids ?? null,
    override_skill_ids: m.override_skill_ids ?? null,
    override_knowledge_base_ids: m.override_knowledge_base_ids ?? null,
    can_delegate: m.can_delegate,
    expanded: false,
  }
}

function draftToCreatePayload(d: MemberDraft, position: number): TeamMemberCreate {
  return {
    agent_id: d.agent_id,
    position,
    override_name: d.override_name.trim() || null,
    override_system_prompt: d.override_system_prompt.trim() || null,
    override_tool_ids: d.override_tool_ids,
    override_mcp_server_ids: d.override_mcp_server_ids,
    override_skill_ids: d.override_skill_ids,
    override_knowledge_base_ids: d.override_knowledge_base_ids,
    can_delegate: d.can_delegate,
  }
}

function toggleInList(list: string[] | null, id: string): string[] | null {
  const current = list ?? []
  const next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id]
  return next
}

export function TeamDialog({ open, onOpenChange, team }: TeamDialogProps) {
  const { data: session } = useSession()
  const { resolvedTheme } = useTheme()
  const agents = usePlaygroundStore((s) => s.agents)
  const teams = usePlaygroundStore((s) => s.teams)
  const setTeams = usePlaygroundStore((s) => s.setTeams)
  const setSelectedTeam = usePlaygroundStore((s) => s.setSelectedTeam)

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [mode, setMode] = useState("coordinate")
  const [members, setMembers] = useState<MemberDraft[]>([])
  const [removedMemberIds, setRemovedMemberIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [sandboxEnabled, setSandboxEnabled] = useState(false)
  const [sandboxRunning, setSandboxRunning] = useState(false)
  const [sandboxLoading, setSandboxLoading] = useState(false)

  const [availableTools, setAvailableTools] = useState<ToolDefinition[]>([])
  const [availableMCPServers, setAvailableMCPServers] = useState<MCPServer[]>([])
  const [availableKBs, setAvailableKBs] = useState<KnowledgeBase[]>([])
  const [availableSkills, setAvailableSkills] = useState<Skill[]>([])

  const isEditing = !!team

  useEffect(() => {
    if (!open) return
    apiClient.listTools().then(setAvailableTools).catch(() => {})
    apiClient.listMCPServers().then(setAvailableMCPServers).catch(() => {})
    apiClient.listKnowledgeBases().then(setAvailableKBs).catch(() => {})
    apiClient.listSkills().then(setAvailableSkills).catch(() => {})
  }, [open])

  useEffect(() => {
    if (open && team) {
      setName(team.name)
      setDescription(team.description || "")
      setMode(team.mode)
      setMembers(team.members.map(memberToDraft))
      setRemovedMemberIds([])
      setSandboxEnabled(team.sandbox_enabled ?? false)
      setSandboxRunning(team.sandbox_container_id != null && team.sandbox_enabled === true)
      setError("")
    } else if (open && !team) {
      resetForm()
    }
  }, [open, team])

  const addMember = (agentId: string) => {
    setMembers((prev) => [
      ...prev,
      {
        tempId: `new-${Date.now()}-${Math.random()}`,
        agent_id: agentId,
        override_name: "",
        override_system_prompt: "",
        override_tool_ids: null,
        override_mcp_server_ids: null,
        override_skill_ids: null,
        override_knowledge_base_ids: null,
        can_delegate: true,
        expanded: false,
      },
    ])
  }

  const removeMember = (tempId: string) => {
    const draft = members.find((m) => m.tempId === tempId)
    if (draft?.memberId) setRemovedMemberIds((prev) => [...prev, draft.memberId!])
    setMembers((prev) => prev.filter((m) => m.tempId !== tempId))
  }

  const updateMember = (tempId: string, patch: Partial<MemberDraft>) => {
    setMembers((prev) => prev.map((m) => (m.tempId === tempId ? { ...m, ...patch } : m)))
  }

  const handleSubmit = async () => {
    if (!session?.accessToken || !name || members.length === 0) return
    setLoading(true)
    setError("")
    try {
      if (isEditing && team) {
        const updated = await updateTeam(session.accessToken, team.id, {
          name,
          description: description || undefined,
          mode,
          sandbox_enabled: sandboxEnabled,
        })
        // Diff member slots against what the team had when the dialog opened:
        // removed slots are deleted, slots with a memberId are patched,
        // brand-new slots (no memberId) are posted.
        for (const id of removedMemberIds) {
          await removeTeamMember(session.accessToken, team.id, id)
        }
        for (let i = 0; i < members.length; i++) {
          const d = members[i]
          const payload = draftToCreatePayload(d, i)
          if (d.memberId) {
            await updateTeamMember(session.accessToken, team.id, d.memberId, payload)
          } else {
            await addTeamMember(session.accessToken, team.id, payload)
          }
        }
        const refreshed = await apiClient.getTeam(team.id)
        setTeams(teams.map((t) => (t.id === refreshed.id ? refreshed : t)))
      } else {
        const newTeam = await createTeam(session.accessToken, {
          name,
          description: description || undefined,
          mode,
          members: members.map((d, i) => draftToCreatePayload(d, i)),
          sandbox_enabled: sandboxEnabled,
        })
        setTeams([...teams, newTeam])
        setSelectedTeam(newTeam.id)
      }

      resetForm()
      onOpenChange(false)
    } catch (err: any) {
      console.error("Failed to save team:", err)
      setError(err?.message || "Failed to save team")
    } finally {
      setLoading(false)
    }
  }

  const resetForm = () => {
    setName("")
    setDescription("")
    setMode("coordinate")
    setMembers([])
    setRemovedMemberIds([])
    setError("")
    setSandboxEnabled(false)
    setSandboxRunning(false)
  }

  const handleSandboxToggle = async () => {
    if (!isEditing || !team) return
    setSandboxLoading(true)
    try {
      if (sandboxRunning) {
        await apiClient.stopTeamSandbox(team.id)
        setSandboxRunning(false)
        const updated = { ...team, sandbox_enabled: sandboxEnabled, sandbox_container_id: null, sandbox_host_port: null }
        setTeams(teams.map((t) => (t.id === team.id ? updated : t)))
      } else {
        const status = await apiClient.startTeamSandbox(team.id)
        setSandboxRunning(status.status === "running")
        const updated = { ...team, sandbox_enabled: true, sandbox_container_id: status.container_id ?? null, sandbox_host_port: status.host_port ?? null }
        setTeams(teams.map((t) => (t.id === team.id ? updated : t)))
      }
    } catch (err: any) {
      console.error("Sandbox toggle failed:", err)
    } finally {
      setSandboxLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showFullscreenButton className="sm:max-w-[70vw] max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Team" : "Create Team"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the team configuration."
              : "Combine multiple agents into a team for complex tasks. The same agent can be added more than once with different roles."}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4 overflow-y-auto flex-1 min-h-0">
          <div className="grid gap-2">
            <Label htmlFor="team-name">Name</Label>
            <Input
              id="team-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Research Team"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="team-desc">Description</Label>
            <Input
              id="team-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A team that researches and summarizes"
            />
          </div>

          <div className="grid gap-2">
            <Label>Mode</Label>
            <Select value={mode} onValueChange={setMode}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="coordinate">Coordinate — Router picks the best agent per message</SelectItem>
                <SelectItem value="route">Route — All agents respond in parallel, synthesizer merges</SelectItem>
                <SelectItem value="collaborate">Collaborate — Agents run in sequence, each builds on the last</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Members Section */}
          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label className="flex items-center gap-1.5">
                <Users2 className="h-3.5 w-3.5" />
                Members ({members.length})
              </Label>
            </div>
            {agents.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Create agents first before building a team.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {agents.map((agent) => (
                    <button
                      key={agent.id}
                      type="button"
                      onClick={() => addMember(agent.id)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs border border-border hover:border-primary/50 hover:bg-primary/5 transition-colors"
                    >
                      <Plus className="h-3 w-3" />
                      {agent.name}
                    </button>
                  ))}
                </div>

                <div className="space-y-2 mt-1">
                  {members.length === 0 ? (
                    <p className="text-xs text-muted-foreground border border-dashed border-border rounded-md p-3 text-center">
                      Click an agent above to add it to this team.
                    </p>
                  ) : (
                    members.map((m) => {
                      const baseAgent = agents.find((a) => a.id === m.agent_id)
                      return (
                        <MemberSlot
                          key={m.tempId}
                          draft={m}
                          baseAgentName={baseAgent?.name ?? "(unknown agent)"}
                          onUpdate={(patch) => updateMember(m.tempId, patch)}
                          onRemove={() => removeMember(m.tempId)}
                          canRemove={members.length > 1}
                          resolvedTheme={resolvedTheme}
                          availableTools={availableTools}
                          availableMCPServers={availableMCPServers}
                          availableKBs={availableKBs}
                          availableSkills={availableSkills}
                        />
                      )
                    })
                  )}
                </div>
              </>
            )}
          </div>

          {/* Docker Sandbox Section */}
          <div className="grid gap-2">
            <Label className="flex items-center gap-1.5">
              <Terminal className="h-3.5 w-3.5 text-emerald-500" />
              Docker Sandbox
            </Label>
            <p className="text-xs text-muted-foreground -mt-1">
              Spin up an isolated Docker container for this team. All agents in the team share the sandbox environment.
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
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={loading || !name || members.length === 0}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {isEditing ? "Save Changes" : "Create Team"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function MemberSlot({
  draft, baseAgentName, onUpdate, onRemove, canRemove, resolvedTheme,
  availableTools, availableMCPServers, availableKBs, availableSkills,
}: {
  draft: MemberDraft
  baseAgentName: string
  onUpdate: (patch: Partial<MemberDraft>) => void
  onRemove: () => void
  canRemove: boolean
  resolvedTheme: string | undefined
  availableTools: ToolDefinition[]
  availableMCPServers: MCPServer[]
  availableKBs: KnowledgeBase[]
  availableSkills: Skill[]
}) {
  const displayName = draft.override_name.trim() || baseAgentName

  return (
    <div className="border border-border rounded-md overflow-hidden">
      <div className="flex items-center gap-2 p-2 bg-muted/30">
        <button
          type="button"
          onClick={() => onUpdate({ expanded: !draft.expanded })}
          className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
        >
          {draft.expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="text-sm font-medium truncate">{displayName}</span>
          {displayName !== baseAgentName && (
            <span className="text-xs text-muted-foreground shrink-0">({baseAgentName})</span>
          )}
        </button>
        <button
          type="button"
          onClick={onRemove}
          disabled={!canRemove}
          title={!canRemove ? "A team needs at least one member" : "Remove"}
          className="p-1 rounded text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {draft.expanded && (
        <div className="p-3 space-y-3 border-t border-border">
          <div className="grid gap-1.5">
            <Label className="text-xs">Display name in this team</Label>
            <Input
              value={draft.override_name}
              onChange={(e) => onUpdate({ override_name: e.target.value })}
              placeholder={`Inherited from ${baseAgentName}`}
              className="h-8 text-xs"
            />
          </div>

          <div className="grid gap-1.5">
            <Label className="text-xs">System prompt override</Label>
            <div className="min-h-24" data-color-mode={resolvedTheme === "dark" ? "dark" : "light"}>
              <MDEditor
                value={draft.override_system_prompt}
                onChange={(v) => onUpdate({ override_system_prompt: v || "" })}
                height={160}
                preview="live"
                textareaProps={{ placeholder: `Inherited from ${baseAgentName}'s own system prompt` }}
              />
            </div>
          </div>

          <OverrideList
            label="Tools"
            inherited="Inherited from the base agent's tools"
            items={availableTools}
            selected={draft.override_tool_ids}
            onChange={(ids) => onUpdate({ override_tool_ids: ids })}
          />
          <OverrideList
            label="MCP Servers"
            inherited="Inherited from the base agent's MCP servers"
            items={availableMCPServers}
            selected={draft.override_mcp_server_ids}
            onChange={(ids) => onUpdate({ override_mcp_server_ids: ids })}
          />
          <OverrideList
            label="Skills"
            inherited="Inherited from the base agent's skills"
            items={availableSkills}
            selected={draft.override_skill_ids}
            onChange={(ids) => onUpdate({ override_skill_ids: ids })}
          />
          <OverrideList
            label="Knowledge Bases"
            inherited="Inherited from the base agent's knowledge bases"
            items={availableKBs}
            selected={draft.override_knowledge_base_ids}
            onChange={(ids) => onUpdate({ override_knowledge_base_ids: ids })}
          />

          <button
            type="button"
            onClick={() => onUpdate({ can_delegate: !draft.can_delegate })}
            className="w-full flex items-center gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left border border-border"
          >
            {draft.can_delegate ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
            ) : (
              <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
            )}
            <span className={draft.can_delegate ? "text-emerald-600 dark:text-emerald-400 font-medium" : "text-muted-foreground"}>
              {draft.can_delegate ? "Can delegate to teammates" : "Cannot delegate further"}
            </span>
          </button>
        </div>
      )}
    </div>
  )
}

function OverrideList({
  label, inherited, items, selected, onChange,
}: {
  label: string
  inherited: string
  items: { id: string; name: string }[]
  selected: string[] | null
  onChange: (ids: string[] | null) => void
}) {
  const isOverriding = selected !== null

  if (items.length === 0) return null

  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between">
        <Label className="text-xs">{label}</Label>
        <button
          type="button"
          onClick={() => onChange(isOverriding ? null : [])}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          {isOverriding ? "Revert to inherited" : "Override"}
        </button>
      </div>
      {!isOverriding ? (
        <p className="text-xs text-muted-foreground/70 italic">{inherited}</p>
      ) : (
        <div className="space-y-1 max-h-32 overflow-y-auto rounded-md border border-border p-1.5">
          {items.map((item) => {
            const isSelected = selected!.includes(item.id)
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onChange(toggleInList(selected, item.id))}
                className="w-full flex items-center gap-2 p-1.5 rounded text-xs hover:bg-muted/50 transition-colors text-left"
              >
                {isSelected ? (
                  <CheckCheck className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
                ) : (
                  <Circle className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />
                )}
                <span className="truncate">{item.name}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
