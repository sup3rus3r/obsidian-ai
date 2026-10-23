"use client"

import { useState } from "react"
import { Users, Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { apiClient } from "@/lib/api-client"
import { usePlaygroundStore } from "@/stores/playground-store"
import type { Team, Agent } from "@/types/playground"

// Inline agent add/remove for an existing team, right from the chat header.
// This is a plain presence toggle (no per-member overrides) — add appends a
// new, un-overridden TeamMember slot for that base agent; remove drops the
// first member slot using it. For per-slot customization (same base agent
// twice with different roles/prompts), use the full Team dialog instead.
export function TeamMembersPopover({ team }: { team: Team }) {
  const agents = usePlaygroundStore((s) => s.agents)
  const teams = usePlaygroundStore((s) => s.teams)
  const setTeams = usePlaygroundStore((s) => s.setTeams)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  const toggleAgent = async (agentId: string) => {
    if (saving) return
    const existingMember = team.members.find((m) => m.agent_id === agentId)
    if (existingMember && team.members.length === 1) return // a team needs at least one member

    setSaving(true)
    try {
      let updatedMembers
      if (existingMember) {
        await apiClient.removeTeamMember(team.id, existingMember.id)
        updatedMembers = team.members.filter((m) => m.id !== existingMember.id)
      } else {
        const created = await apiClient.addTeamMember(team.id, {
          agent_id: agentId,
          position: team.members.length,
        })
        updatedMembers = [...team.members, created]
      }
      const updated = { ...team, members: updatedMembers }
      setTeams(teams.map((t) => (t.id === team.id ? updated : t)))
    } catch (err) {
      console.error("Failed to update team members:", err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1.5 text-xs px-2">
          <Users className="h-3.5 w-3.5" />
          {team.members.length}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-0">
        <div className="px-3 py-2 border-b flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Team Members</p>
          {saving && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
        <div className="max-h-64 overflow-y-auto py-1">
          {agents.length === 0 ? (
            <p className="text-xs text-muted-foreground px-3 py-2">No agents available.</p>
          ) : (
            agents.map((a: Agent) => {
              const isMember = team.members.some((m) => m.agent_id === a.id)
              const isOnlyMember = isMember && team.members.length === 1
              return (
                <button
                  key={a.id}
                  onClick={() => toggleAgent(a.id)}
                  disabled={saving || isOnlyMember}
                  title={isOnlyMember ? "A team needs at least one member" : undefined}
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-muted disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <div
                    className={`h-4 w-4 rounded border flex items-center justify-center shrink-0 ${
                      isMember ? "bg-primary border-primary" : "border-input"
                    }`}
                  >
                    {isMember && <Check className="h-3 w-3 text-primary-foreground" />}
                  </div>
                  <span className="truncate">{a.name}</span>
                </button>
              )
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
