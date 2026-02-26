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
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useSession } from "next-auth/react"
import { apiClient } from "@/lib/api-client"
import { useDashboardStore } from "@/stores/dashboard-store"
import { usePlaygroundStore } from "@/stores/playground-store"
import { Loader2, Plus, Trash2 } from "lucide-react"
import type { Agent } from "@/types/playground"

interface WorkflowDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agents: Agent[]
  onCreated?: () => void
}

interface StepInput {
  agent_id: string
  task: string
}

export function WorkflowDialog({ open, onOpenChange, agents, onCreated }: WorkflowDialogProps) {
  const { data: session } = useSession()

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [steps, setSteps] = useState<StepInput[]>([{ agent_id: "", task: "" }])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const addStep = () => {
    setSteps([...steps, { agent_id: "", task: "" }])
  }

  const removeStep = (index: number) => {
    if (steps.length <= 1) return
    setSteps(steps.filter((_, i) => i !== index))
  }

  const updateStep = (index: number, field: keyof StepInput, value: string) => {
    const updated = [...steps]
    updated[index] = { ...updated[index], [field]: value }
    setSteps(updated)
  }

  const handleCreate = async () => {
    if (!session?.accessToken || !name || steps.length === 0) return
    const validSteps = steps.filter((s) => s.agent_id && s.task)
    if (validSteps.length === 0) return

    setLoading(true)
    setError("")
    try {
      await apiClient.createWorkflow({
        name,
        description: description || undefined,
        steps: validSteps.map((s, i) => ({
          agent_id: s.agent_id,
          task: s.task,
          order: i + 1,
        })),
      })
      resetForm()
      onOpenChange(false)
      onCreated?.()
    } catch (err: any) {
      console.error("Failed to create workflow:", err)
      setError(err?.message || "Failed to create workflow")
    } finally {
      setLoading(false)
    }
  }

  const resetForm = () => {
    setName("")
    setDescription("")
    setSteps([{ agent_id: "", task: "" }])
    setError("")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>Create Workflow</DialogTitle>
          <DialogDescription>
            Define a sequence of agent tasks that execute in order.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4 max-h-[60vh] overflow-y-auto">
          <div className="grid gap-2">
            <Label htmlFor="workflow-name">Name</Label>
            <Input
              id="workflow-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Content Pipeline"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="workflow-desc">Description</Label>
            <Textarea
              id="workflow-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="A workflow that processes content through multiple agents..."
              rows={2}
              className="resize-none"
            />
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>Steps</Label>
              <Button variant="ghost" size="sm" className="h-7 text-xs gap-1" onClick={addStep}>
                <Plus className="h-3 w-3" />
                Add Step
              </Button>
            </div>

            <div className="space-y-3">
              {steps.map((step, index) => (
                <div key={index} className="flex gap-2 items-start p-3 rounded-md border border-border bg-muted/30">
                  <span className="text-xs text-muted-foreground font-mono mt-2.5 w-5 shrink-0">
                    {index + 1}.
                  </span>
                  <div className="flex-1 space-y-2">
                    <Select
                      value={step.agent_id}
                      onValueChange={(v) => updateStep(index, "agent_id", v)}
                    >
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select agent..." />
                      </SelectTrigger>
                      <SelectContent>
                        {agents.map((a) => (
                          <SelectItem key={a.id} value={a.id}>
                            {a.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input
                      value={step.task}
                      onChange={(e) => updateStep(index, "task", e.target.value)}
                      placeholder="Task description..."
                      className="h-8 text-xs"
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6 mt-1 shrink-0"
                    onClick={() => removeStep(index)}
                    disabled={steps.length <= 1}
                  >
                    <Trash2 className="h-3 w-3 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleCreate}
            disabled={loading || !name || steps.every((s) => !s.agent_id || !s.task)}
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Create Workflow
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
