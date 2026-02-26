"use client"

import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { apiClient } from "@/lib/api-client"
import { toast } from "sonner"
import type { Workflow, WorkflowSchedule } from "@/types/playground"
import {
  Plus,
  Trash2,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  CalendarClock,
  ToggleLeft,
  ToggleRight,
} from "lucide-react"

interface WorkflowScheduleDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workflow: Workflow | null
}

function formatDatetime(iso?: string): string {
  if (!iso) return "—"
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

interface AddScheduleFormProps {
  workflowId: string
  onSaved: (schedule: WorkflowSchedule) => void
  onCancel: () => void
}

function AddScheduleForm({ workflowId, onSaved, onCancel }: AddScheduleFormProps) {
  const [name, setName] = useState("")
  const [cronExpr, setCronExpr] = useState("")
  const [inputText, setInputText] = useState("")
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !cronExpr.trim()) return
    setSaving(true)
    try {
      const created = await apiClient.createWorkflowSchedule(workflowId, {
        name: name.trim(),
        cron_expr: cronExpr.trim(),
        input_text: inputText.trim() || undefined,
        is_active: true,
      })
      onSaved(created)
      toast.success("Schedule created")
    } catch (err: any) {
      toast.error(err.message || "Failed to create schedule")
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3 rounded-lg border border-border bg-muted/30 p-4">
      <p className="text-xs font-medium text-foreground">New Schedule</p>

      <div className="space-y-1">
        <Label className="text-xs">Name</Label>
        <Input
          placeholder="Daily morning run"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 text-sm"
          required
        />
      </div>

      <div className="space-y-1">
        <Label className="text-xs">
          Cron Expression{" "}
          <a
            href="https://crontab.guru"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline"
          >
            (help)
          </a>
        </Label>
        <Input
          placeholder="0 9 * * 1-5"
          value={cronExpr}
          onChange={(e) => setCronExpr(e.target.value)}
          className="h-8 font-mono text-sm"
          required
        />
        <p className="text-[10px] text-muted-foreground">
          5-field cron: minute hour day month weekday
        </p>
      </div>

      <div className="space-y-1">
        <Label className="text-xs">Input text (optional)</Label>
        <Textarea
          placeholder="The input passed to the first workflow step"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          className="text-sm min-h-[60px] resize-none"
        />
      </div>

      <div className="flex gap-2 justify-end">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={saving || !name.trim() || !cronExpr.trim()}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
          Create
        </Button>
      </div>
    </form>
  )
}

interface ScheduleRowProps {
  schedule: WorkflowSchedule
  onDeleted: (id: string) => void
  onToggled: (updated: WorkflowSchedule) => void
}

function ScheduleRow({ schedule, onDeleted, onToggled }: ScheduleRowProps) {
  const [deleting, setDeleting] = useState(false)
  const [toggling, setToggling] = useState(false)

  const handleDelete = async () => {
    if (deleting) return
    setDeleting(true)
    try {
      await apiClient.deleteWorkflowSchedule(schedule.id)
      onDeleted(schedule.id)
      toast.success("Schedule deleted")
    } catch (err: any) {
      toast.error(err.message || "Failed to delete schedule")
      setDeleting(false)
    }
  }

  const handleToggle = async () => {
    setToggling(true)
    try {
      const updated = await apiClient.updateWorkflowSchedule(schedule.id, {
        is_active: !schedule.is_active,
      })
      onToggled(updated)
    } catch (err: any) {
      toast.error(err.message || "Failed to update schedule")
    } finally {
      setToggling(false)
    }
  }

  return (
    <div className="flex items-start gap-3 rounded-lg border border-border p-3">
      <CalendarClock className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />

      <div className="flex-1 min-w-0 space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium truncate">{schedule.name}</span>
          <Badge
            variant={schedule.is_active ? "secondary" : "outline"}
            className="text-[10px] px-1.5 py-0 shrink-0"
          >
            {schedule.is_active ? "active" : "paused"}
          </Badge>
        </div>

        <div className="flex items-center gap-1.5">
          <code className="text-[11px] font-mono text-muted-foreground bg-muted rounded px-1">
            {schedule.cron_expr}
          </code>
        </div>

        {schedule.input_text && (
          <p className="text-[11px] text-muted-foreground truncate">
            Input: {schedule.input_text}
          </p>
        )}

        <div className="flex gap-3 text-[10px] text-muted-foreground">
          <span>Next: {formatDatetime(schedule.next_run_at)}</span>
          {schedule.last_run_at && (
            <span>Last: {formatDatetime(schedule.last_run_at)}</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleToggle}
          disabled={toggling}
          className="h-7 w-7"
          title={schedule.is_active ? "Pause" : "Resume"}
        >
          {toggling ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : schedule.is_active ? (
            <ToggleRight className="h-3.5 w-3.5 text-emerald-500" />
          ) : (
            <ToggleLeft className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleDelete}
          disabled={deleting}
          className="h-7 w-7"
        >
          {deleting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          )}
        </Button>
      </div>
    </div>
  )
}

export function WorkflowScheduleDialog({
  open,
  onOpenChange,
  workflow,
}: WorkflowScheduleDialogProps) {
  const [schedules, setSchedules] = useState<WorkflowSchedule[]>([])
  const [loading, setLoading] = useState(false)
  const [showAddForm, setShowAddForm] = useState(false)

  useEffect(() => {
    if (open && workflow) {
      setLoading(true)
      apiClient
        .listWorkflowSchedules(workflow.id)
        .then((data) => setSchedules(data))
        .catch(() => setSchedules([]))
        .finally(() => setLoading(false))
    } else {
      setSchedules([])
      setShowAddForm(false)
    }
  }, [open, workflow])

  const handleSaved = (schedule: WorkflowSchedule) => {
    setSchedules((prev) => [schedule, ...prev])
    setShowAddForm(false)
  }

  const handleDeleted = (id: string) => {
    setSchedules((prev) => prev.filter((s) => s.id !== id))
  }

  const handleToggled = (updated: WorkflowSchedule) => {
    setSchedules((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-emerald-500" />
            Schedules — {workflow?.name}
          </DialogTitle>
          <DialogDescription>
            Workflow runs automatically on a cron schedule, even when no browser is open.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {loading ? (
            <div className="flex justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              {schedules.length === 0 && !showAddForm && (
                <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
                  <Clock className="h-8 w-8" />
                  <p className="text-sm">No schedules yet</p>
                  <p className="text-xs text-center max-w-xs">
                    Create a cron schedule to run this workflow automatically in the background.
                  </p>
                </div>
              )}

              {schedules.map((s) => (
                <ScheduleRow
                  key={s.id}
                  schedule={s}
                  onDeleted={handleDeleted}
                  onToggled={handleToggled}
                />
              ))}

              {showAddForm && workflow ? (
                <AddScheduleForm
                  workflowId={workflow.id}
                  onSaved={handleSaved}
                  onCancel={() => setShowAddForm(false)}
                />
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full"
                  onClick={() => setShowAddForm(true)}
                >
                  <Plus className="h-3.5 w-3.5 mr-1.5" />
                  Add Schedule
                </Button>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
