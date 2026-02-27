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
import { usePlaygroundStore } from "@/stores/playground-store"
import { Loader2, Check } from "lucide-react"
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

  const isEditing = !!team

  // Populate fields when editing an existing team
  useEffect(() => {
    if (open && team) {
      setName(team.name)
      setDescription(team.description || "")
      setMode(team.mode)
      setSelectedAgentIds(team.agent_ids)
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
