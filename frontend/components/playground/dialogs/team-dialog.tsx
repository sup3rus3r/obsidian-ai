"use client"

import { useState } from "react"
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
import { createTeam } from "@/app/api/playground"
import { usePlaygroundStore } from "@/stores/playground-store"
import { Loader2, Check } from "lucide-react"

interface TeamDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function TeamDialog({ open, onOpenChange }: TeamDialogProps) {
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

  const toggleAgent = (agentId: string) => {
    setSelectedAgentIds((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId]
    )
  }

  const handleCreate = async () => {
    if (!session?.accessToken || !name || selectedAgentIds.length === 0) return
    setLoading(true)
    setError("")
    try {
      const newTeam = await createTeam(session.accessToken, {
        name,
        description: description || undefined,
        mode,
        agent_ids: selectedAgentIds,
      })
      setTeams([...teams, newTeam])
      setSelectedTeam(newTeam.id)
      resetForm()
      onOpenChange(false)
    } catch (err: any) {
      console.error("Failed to create team:", err)
      setError(err?.message || "Failed to create team")
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
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Create Team</DialogTitle>
          <DialogDescription>
            Combine multiple agents into a team for complex tasks.
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
                <SelectItem value="coordinate">Coordinate - Router picks the best agent</SelectItem>
                <SelectItem value="route">Route - Direct routing to specialist</SelectItem>
                <SelectItem value="collaborate">Collaborate - Sequential chain</SelectItem>
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
                      className={`h-4 w-4 rounded border flex items-center justify-center flex-shrink-0 ${
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
            onClick={handleCreate}
            disabled={loading || !name || selectedAgentIds.length === 0}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Create Team
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
