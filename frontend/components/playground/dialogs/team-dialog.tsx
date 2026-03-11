"use client"

import { useState, useEffect } from "react"
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
import { createTeam, updateTeam } from "@/app/api/playground"
import { apiClient } from "@/lib/api-client"
import { usePlaygroundStore } from "@/stores/playground-store"
import { Loader2, Check, CheckCircle2, Circle, Terminal, Play, Square } from "lucide-react"
import type { Team } from "@/types/playground"

interface TeamDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  team?: Team | null
}

export function TeamDialog({ open, onOpenChange, team }: TeamDialogProps) {
  const { data: session } = useSession()
  const agents = usePlaygroundStore((s) => s.agents)
  const teams = usePlaygroundStore((s) => s.teams)
  const setTeams = usePlaygroundStore((s) => s.setTeams)
  const setSelectedTeam = usePlaygroundStore((s) => s.setSelectedTeam)

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [mode, setMode] = useState("coordinate")
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [sandboxEnabled, setSandboxEnabled] = useState(false)
  const [sandboxRunning, setSandboxRunning] = useState(false)
  const [sandboxLoading, setSandboxLoading] = useState(false)

  const isEditing = !!team

  // Populate fields when editing an existing team
  useEffect(() => {
    if (open && team) {
      setName(team.name)
      setDescription(team.description || "")
      setMode(team.mode)
      setSelectedAgentIds(team.agent_ids)
      setSandboxEnabled(team.sandbox_enabled ?? false)
      setSandboxRunning(team.sandbox_container_id != null && team.sandbox_enabled === true)
      setError("")
    } else if (open && !team) {
      resetForm()
    }
  }, [open, team])

  const toggleAgent = (agentId: string) => {
    setSelectedAgentIds((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId]
    )
  }

  const handleSubmit = async () => {
    if (!session?.accessToken || !name || selectedAgentIds.length === 0) return
    setLoading(true)
    setError("")
    try {
      const payload = {
        name,
        description: description || undefined,
        mode,
        agent_ids: selectedAgentIds,
        sandbox_enabled: sandboxEnabled,
      }

      if (isEditing && team) {
        const updated = await updateTeam(session.accessToken, team.id, payload)
        setTeams(teams.map((t) => (t.id === updated.id ? updated : t)))
      } else {
        const newTeam = await createTeam(session.accessToken, payload)
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
    setSelectedAgentIds([])
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
      <DialogContent className="sm:max-w-125">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit Team" : "Create Team"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the team configuration."
              : "Combine multiple agents into a team for complex tasks."}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
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

          <div className="grid gap-2">
            <Label>Agents ({selectedAgentIds.length} selected)</Label>
            {agents.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Create agents first before building a team.
              </p>
            ) : (
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {agents.map((agent) => (
                  <button
                    key={agent.id}
                    onClick={() => toggleAgent(agent.id)}
                    className={`w-full flex items-center gap-2 px-3 py-2 rounded-md text-left text-sm transition-colors ${
                      selectedAgentIds.includes(agent.id)
                        ? "bg-primary/10 text-primary"
                        : "hover:bg-muted"
                    }`}
                  >
                    <div
                      className={`h-4 w-4 rounded border flex items-center justify-center shrink-0 ${
                        selectedAgentIds.includes(agent.id)
                          ? "bg-primary border-primary"
                          : "border-input"
                      }`}
                    >
                      {selectedAgentIds.includes(agent.id) && (
                        <Check className="h-3 w-3 text-primary-foreground" />
                      )}
                    </div>
                    <span className="truncate">{agent.name}</span>
                  </button>
                ))}
              </div>
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
            disabled={loading || !name || selectedAgentIds.length === 0}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {isEditing ? "Save Changes" : "Create Team"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
