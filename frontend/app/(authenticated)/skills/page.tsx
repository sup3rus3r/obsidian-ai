"use client"

import { useState, useEffect } from "react"
import dynamic from "next/dynamic"
import { useSession } from "next-auth/react"
import { useTheme } from "next-themes"
import { Sparkles, Plus, Trash2, Pencil, Loader2, Search, Paperclip, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import "@uiw/react-md-editor/markdown-editor.css"
import { AnimatedList, AnimatedListItem } from "@/components/ui/animated-list"
import { AppRoutes } from "@/app/api/routes"
import { useConfirm } from "@/hooks/use-confirm"
import { apiClient } from "@/lib/api-client"
import type { SkillFile } from "@/types/playground"

const MDEditor = dynamic(() => import("@uiw/react-md-editor"), { ssr: false })

interface SkillEntry {
  id: string
  name: string
  description: string | null
  instructions: string
  file_count: number
  created_at: string
  updated_at: string | null
}

interface StagedFile {
  filename: string
  file_data: string
}

function formatFileSize(bytes: number | null): string {
  if (bytes == null) return ""
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export default function SkillsPage() {
  const { data: session } = useSession()
  const { resolvedTheme } = useTheme()
  const [skills, setSkills] = useState<SkillEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [editingSkill, setEditingSkill] = useState<SkillEntry | null>(null)
  const [previewSkill, setPreviewSkill] = useState<SkillEntry | null>(null)
  const [ConfirmDeleteDialog, confirmDelete] = useConfirm({
    title: "Delete skill",
    description: "This will permanently delete this skill. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  // Create form
  const [createName, setCreateName] = useState("")
  const [createDescription, setCreateDescription] = useState("")
  const [createInstructions, setCreateInstructions] = useState("")
  const [creating, setCreating] = useState(false)
  const [stagedFiles, setStagedFiles] = useState<StagedFile[]>([])

  // Edit form
  const [editName, setEditName] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [editInstructions, setEditInstructions] = useState("")
  const [editing, setEditing] = useState(false)
  const [editFiles, setEditFiles] = useState<SkillFile[]>([])
  const [editFilesLoading, setEditFilesLoading] = useState(false)
  const [uploadingFile, setUploadingFile] = useState(false)

  useEffect(() => {
    if (session?.accessToken) fetchSkills()
  }, [session?.accessToken])

  const fetchSkills = async () => {
    setLoading(true)
    try {
      const res = await fetch(AppRoutes.ListSkills(), {
        headers: { Authorization: `Bearer ${session?.accessToken}` },
      })
      if (res.ok) {
        const data = await res.json()
        setSkills(data.skills || [])
      }
    } catch (e) {
      console.error("Failed to fetch skills:", e)
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!createName.trim() || !createInstructions.trim()) {
      toast.error("Name and instructions are required")
      return
    }
    setCreating(true)
    try {
      const res = await fetch(AppRoutes.CreateSkill(), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.accessToken}` },
        body: JSON.stringify({
          name: createName.trim(),
          description: createDescription.trim() || null,
          instructions: createInstructions.trim(),
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to create skill" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const created = await res.json()
      if (stagedFiles.length > 0) {
        for (const f of stagedFiles) {
          try {
            await apiClient.addSkillFile(created.id, f.filename, f.file_data)
          } catch (e: any) {
            toast.error(`Failed to upload ${f.filename}: ${e.message || "unknown error"}`)
          }
        }
      }
      toast.success("Skill saved to vault")
      setShowCreateDialog(false)
      setCreateName("")
      setCreateDescription("")
      setCreateInstructions("")
      setStagedFiles([])
      await fetchSkills()
    } catch (e: any) {
      toast.error(e.message || "Failed to create skill")
    } finally {
      setCreating(false)
    }
  }

  const handleStageFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    const files = await Promise.all(
      Array.from(fileList).map(async (file) => ({
        filename: file.name,
        file_data: await readFileAsDataURL(file),
      })),
    )
    setStagedFiles((prev) => [...prev, ...files])
  }

  const removeStagedFile = (filename: string) => {
    setStagedFiles((prev) => prev.filter((f) => f.filename !== filename))
  }

  const fetchEditFiles = async (skillId: string) => {
    setEditFilesLoading(true)
    try {
      const files = await apiClient.listSkillFiles(skillId)
      setEditFiles(files)
    } catch (e) {
      console.error("Failed to fetch skill files:", e)
    } finally {
      setEditFilesLoading(false)
    }
  }

  const handleUploadEditFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0 || !editingSkill) return
    setUploadingFile(true)
    try {
      for (const file of Array.from(fileList)) {
        const dataUrl = await readFileAsDataURL(file)
        const created = await apiClient.addSkillFile(editingSkill.id, file.name, dataUrl)
        setEditFiles((prev) => [...prev, created])
      }
      await fetchSkills()
    } catch (e: any) {
      toast.error(e.message || "Failed to upload file")
    } finally {
      setUploadingFile(false)
    }
  }

  const handleDeleteEditFile = async (fileId: string) => {
    if (!editingSkill) return
    try {
      await apiClient.deleteSkillFile(editingSkill.id, fileId)
      setEditFiles((prev) => prev.filter((f) => f.id !== fileId))
      await fetchSkills()
    } catch (e: any) {
      toast.error(e.message || "Failed to remove file")
    }
  }

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingSkill) return
    const updates: Record<string, any> = {}
    if (editName.trim() !== editingSkill.name) updates.name = editName.trim()
    if (editDescription !== (editingSkill.description || "")) updates.description = editDescription.trim() || null
    if (editInstructions.trim() !== editingSkill.instructions) updates.instructions = editInstructions.trim()
    if (Object.keys(updates).length === 0) {
      toast.error("No changes to save")
      return
    }
    setEditing(true)
    try {
      const res = await fetch(AppRoutes.UpdateSkill(editingSkill.id), {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.accessToken}` },
        body: JSON.stringify(updates),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to update skill" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Skill updated")
      setShowEditDialog(false)
      setEditingSkill(null)
      await fetchSkills()
    } catch (e: any) {
      toast.error(e.message || "Failed to update skill")
    } finally {
      setEditing(false)
    }
  }

  const handleDelete = async (id: string, name: string) => {
    const ok = await confirmDelete()
    if (!ok) return
    try {
      const res = await fetch(AppRoutes.DeleteSkill(id), {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session?.accessToken}` },
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to delete skill" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Skill deleted")
      await fetchSkills()
    } catch (e: any) {
      toast.error(e.message || "Failed to delete skill")
    }
  }

  const openEditDialog = (skill: SkillEntry) => {
    setEditingSkill(skill)
    setEditName(skill.name)
    setEditDescription(skill.description || "")
    setEditInstructions(skill.instructions)
    setEditFiles([])
    setShowEditDialog(true)
    fetchEditFiles(skill.id)
  }

  const filteredSkills = skills.filter((s) => {
    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    return s.name.toLowerCase().includes(q) || (s.description || "").toLowerCase().includes(q)
  })

  return (
    <div className="h-full overflow-y-auto p-8 w-full space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
            <Sparkles className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-medium tracking-[-0.016em]">Skills</h1>
              <Badge variant="secondary">{skills.length}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Reusable instruction bundles for Claude agents on an Anthropic endpoint
            </p>
          </div>
        </div>
        <Button onClick={() => setShowCreateDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          New Skill
        </Button>
      </div>

      {/* Search */}
      {skills.length > 0 && (
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search skills..."
            className="w-full pl-9"
          />
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            <p className="text-sm text-muted-foreground">Loading skills...</p>
          </div>
        </div>
      ) : filteredSkills.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <Sparkles className="h-10 w-10 text-muted-foreground" />
          <div>
            <p className="text-base font-medium">
              {searchQuery ? "No skills match your search" : "No skills saved yet"}
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              {searchQuery
                ? "Try different keywords"
                : "Save reusable skill instructions to attach to Claude agents"}
            </p>
          </div>
          {!searchQuery && (
            <Button variant="outline" onClick={() => setShowCreateDialog(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add your first skill
            </Button>
          )}
        </div>
      ) : (
        <AnimatedList className="space-y-2">
          {filteredSkills.map((skill) => (
            <AnimatedListItem key={skill.id}>
              <Card
                className="group cursor-pointer hover:border-primary/50 transition-colors"
                onClick={() => setPreviewSkill(skill)}
              >
                <CardContent className="flex items-start gap-4 py-3 px-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm">{skill.name}</p>
                      {skill.file_count > 0 && (
                        <Badge variant="outline" className="gap-1 text-xs font-normal">
                          <Paperclip className="h-3 w-3" />
                          {skill.file_count}
                        </Badge>
                      )}
                    </div>
                    {skill.description && (
                      <p className="text-sm text-muted-foreground mt-0.5">{skill.description}</p>
                    )}
                    <p className="text-sm text-muted-foreground mt-1.5 line-clamp-2 font-mono">
                      {skill.instructions}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8"
                      onClick={(e) => { e.stopPropagation(); openEditDialog(skill) }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={(e) => { e.stopPropagation(); handleDelete(skill.id, skill.name) }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </AnimatedListItem>
          ))}
        </AnimatedList>
      )}

      {/* Preview Dialog */}
      <Dialog open={!!previewSkill} onOpenChange={(o) => { if (!o) setPreviewSkill(null) }}>
        <DialogContent showFullscreenButton className="max-w-2xl max-h-[85vh] flex flex-col">
          <DialogHeader className="shrink-0">
            <DialogTitle>{previewSkill?.name}</DialogTitle>
            {previewSkill?.description && (
              <DialogDescription>{previewSkill.description}</DialogDescription>
            )}
          </DialogHeader>
          <div className="border rounded-lg p-3 bg-muted flex-1 min-h-32 overflow-y-auto">
            <pre className="text-sm font-mono whitespace-pre-wrap break-words">
              {previewSkill?.instructions}
            </pre>
          </div>
          <DialogFooter className="shrink-0">
            <Button variant="outline" onClick={() => {
              if (previewSkill) { openEditDialog(previewSkill); setPreviewSkill(null) }
            }}>
              <Pencil className="h-4 w-4 mr-2" />
              Edit
            </Button>
            <Button onClick={() => setPreviewSkill(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent
          showFullscreenButton
          className="max-w-[70vw] max-h-[85vh] flex flex-col p-0 gap-0"
        >
          <DialogHeader className="px-6 pt-6 pb-4">
            <DialogTitle>New Skill</DialogTitle>
            <DialogDescription>
              Save a reusable skill to your vault. Skills are only applied to agents using a Claude
              model on an Anthropic endpoint.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="flex flex-col flex-1 min-h-0">
            <div className="flex flex-col flex-1 min-h-0 gap-4 px-6 overflow-y-auto">
              <div className="space-y-2 shrink-0">
                <Label htmlFor="create-name">Name</Label>
                <Input
                  id="create-name"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="e.g., PDF report generation"
                  required
                />
              </div>
              <div className="space-y-2 shrink-0">
                <Label htmlFor="create-desc">Description (Optional)</Label>
                <Input
                  id="create-desc"
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  placeholder="Short summary shown before the skill is loaded"
                />
              </div>
              <div className="flex flex-col flex-1 min-h-0 gap-2">
                <Label htmlFor="create-instructions" className="shrink-0">Instructions</Label>
                <div className="flex-1 min-h-32 overflow-y-auto" data-color-mode={resolvedTheme === "dark" ? "dark" : "light"}>
                  <MDEditor
                    value={createInstructions}
                    onChange={(v) => setCreateInstructions(v || "")}
                    height="100%"
                    preview="live"
                    textareaProps={{ id: "create-instructions", placeholder: "Detailed instructions the model should follow when this skill is relevant...", required: true }}
                  />
                </div>
              </div>
              <div className="space-y-2 shrink-0 pb-4">
                <Label htmlFor="create-files" className="flex items-center gap-1.5">
                  <Paperclip className="h-3.5 w-3.5" />
                  Files (Optional)
                </Label>
                <Input
                  id="create-files"
                  type="file"
                  multiple
                  onChange={(e) => { handleStageFiles(e.target.files); e.target.value = "" }}
                />
                {stagedFiles.length > 0 && (
                  <div className="space-y-1 rounded-md border border-border p-2">
                    {stagedFiles.map((f) => (
                      <div key={f.filename} className="flex items-center justify-between gap-2 text-xs px-1">
                        <span className="truncate">{f.filename}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-muted-foreground">will be uploaded after saving</span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            className="h-6 w-6"
                            onClick={() => removeStagedFile(f.filename)}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <p className="text-xs text-muted-foreground">
                  Files are available to this skill's agent only when its sandbox is running — they're added when the sandbox starts, not retroactively while it's already running.
                </p>
              </div>
            </div>
            <DialogFooter className="px-6 py-4 border-t border-border">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setShowCreateDialog(false)
                  setCreateName("")
                  setCreateDescription("")
                  setCreateInstructions("")
                  setStagedFiles([])
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={creating}>
                {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save to Vault
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent
          showFullscreenButton
          className="max-w-[70vw] max-h-[85vh] flex flex-col p-0 gap-0"
        >
          <DialogHeader className="px-6 pt-6 pb-4">
            <DialogTitle>Edit Skill</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleEdit} className="flex flex-col flex-1 min-h-0">
            <div className="flex flex-col flex-1 min-h-0 gap-4 px-6 overflow-y-auto">
              <div className="space-y-2 shrink-0">
                <Label htmlFor="edit-name">Name</Label>
                <Input
                  id="edit-name"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Skill name"
                  required
                />
              </div>
              <div className="space-y-2 shrink-0">
                <Label htmlFor="edit-desc">Description</Label>
                <Input
                  id="edit-desc"
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder="Short summary"
                />
              </div>
              <div className="flex flex-col flex-1 min-h-0 gap-2">
                <Label htmlFor="edit-instructions" className="shrink-0">Instructions</Label>
                <div className="flex-1 min-h-32 overflow-y-auto" data-color-mode={resolvedTheme === "dark" ? "dark" : "light"}>
                  <MDEditor
                    value={editInstructions}
                    onChange={(v) => setEditInstructions(v || "")}
                    height="100%"
                    preview="live"
                    textareaProps={{ id: "edit-instructions", required: true }}
                  />
                </div>
              </div>
              <div className="space-y-2 shrink-0 pb-4">
                <Label htmlFor="edit-files" className="flex items-center gap-1.5">
                  <Paperclip className="h-3.5 w-3.5" />
                  Files
                </Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="edit-files"
                    type="file"
                    multiple
                    disabled={uploadingFile}
                    onChange={(e) => { handleUploadEditFiles(e.target.files); e.target.value = "" }}
                  />
                  {uploadingFile && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />}
                </div>
                {editFilesLoading ? (
                  <p className="text-xs text-muted-foreground">Loading files...</p>
                ) : editFiles.length > 0 ? (
                  <div className="space-y-1 rounded-md border border-border p-2">
                    {editFiles.map((f) => (
                      <div key={f.id} className="flex items-center justify-between gap-2 text-xs px-1">
                        <span className="truncate">{f.filename}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-muted-foreground">{formatFileSize(f.file_size)}</span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon-sm"
                            className="h-6 w-6 text-destructive hover:text-destructive"
                            onClick={() => handleDeleteEditFile(f.id)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
                <p className="text-xs text-muted-foreground">
                  Files are available to this skill's agent only when its sandbox is running — they're added when the sandbox starts, not retroactively while it's already running.
                </p>
              </div>
            </div>
            <DialogFooter className="px-6 py-4 border-t border-border">
              <Button
                type="button"
                variant="outline"
                onClick={() => { setShowEditDialog(false); setEditingSkill(null); setEditFiles([]) }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={editing}>
                {editing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save Changes
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDeleteDialog />
    </div>
  )
}
