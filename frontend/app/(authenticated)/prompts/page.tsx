"use client"

import { useState, useEffect } from "react"
import { useSession } from "next-auth/react"
import { BookMarked, Plus, Trash2, Pencil, Loader2, Search } from "lucide-react"
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
import { Textarea } from "@/components/ui/textarea"
import { AnimatedList, AnimatedListItem } from "@/components/ui/animated-list"
import { AppRoutes } from "@/app/api/routes"

interface PromptEntry {
  id: string
  name: string
  description: string | null
  content: string
  created_at: string
  updated_at: string | null
}

export default function PromptsPage() {
  const { data: session } = useSession()
  const [prompts, setPrompts] = useState<PromptEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [editingPrompt, setEditingPrompt] = useState<PromptEntry | null>(null)
  const [previewPrompt, setPreviewPrompt] = useState<PromptEntry | null>(null)

  // Create form
  const [createName, setCreateName] = useState("")
  const [createDescription, setCreateDescription] = useState("")
  const [createContent, setCreateContent] = useState("")
  const [creating, setCreating] = useState(false)

  // Edit form
  const [editName, setEditName] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [editContent, setEditContent] = useState("")
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (session?.accessToken) fetchPrompts()
  }, [session?.accessToken])

  const fetchPrompts = async () => {
    setLoading(true)
    try {
      const res = await fetch(AppRoutes.ListPrompts(), {
        headers: { Authorization: `Bearer ${session?.accessToken}` },
      })
      if (res.ok) {
        const data = await res.json()
        setPrompts(data.prompts || [])
      }
    } catch (e) {
      console.error("Failed to fetch prompts:", e)
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!createName.trim() || !createContent.trim()) {
      toast.error("Name and content are required")
      return
    }
    setCreating(true)
    try {
      const res = await fetch(AppRoutes.CreatePrompt(), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.accessToken}` },
        body: JSON.stringify({
          name: createName.trim(),
          description: createDescription.trim() || null,
          content: createContent.trim(),
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to create prompt" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Prompt saved to vault")
      setShowCreateDialog(false)
      setCreateName("")
      setCreateDescription("")
      setCreateContent("")
      await fetchPrompts()
    } catch (e: any) {
      toast.error(e.message || "Failed to create prompt")
    } finally {
      setCreating(false)
    }
  }

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingPrompt) return
    const updates: Record<string, any> = {}
    if (editName.trim() !== editingPrompt.name) updates.name = editName.trim()
    if (editDescription !== (editingPrompt.description || "")) updates.description = editDescription.trim() || null
    if (editContent.trim() !== editingPrompt.content) updates.content = editContent.trim()
    if (Object.keys(updates).length === 0) {
      toast.error("No changes to save")
      return
    }
    setEditing(true)
    try {
      const res = await fetch(AppRoutes.UpdatePrompt(editingPrompt.id), {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.accessToken}` },
        body: JSON.stringify(updates),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to update prompt" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Prompt updated")
      setShowEditDialog(false)
      setEditingPrompt(null)
      await fetchPrompts()
    } catch (e: any) {
      toast.error(e.message || "Failed to update prompt")
    } finally {
      setEditing(false)
    }
  }

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return
    try {
      const res = await fetch(AppRoutes.DeletePrompt(id), {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session?.accessToken}` },
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to delete prompt" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Prompt deleted")
      await fetchPrompts()
    } catch (e: any) {
      toast.error(e.message || "Failed to delete prompt")
    }
  }

  const openEditDialog = (prompt: PromptEntry) => {
    setEditingPrompt(prompt)
    setEditName(prompt.name)
    setEditDescription(prompt.description || "")
    setEditContent(prompt.content)
    setShowEditDialog(true)
  }

  const filteredPrompts = prompts.filter((p) => {
    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    return p.name.toLowerCase().includes(q) || (p.description || "").toLowerCase().includes(q)
  })

  return (
    <div className="h-full w-full overflow-y-auto p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
            <BookMarked className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">Prompt Vault</h1>
              <Badge variant="secondary" className="text-xs">{prompts.length}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Reusable system prompt templates for your agents
            </p>
          </div>
        </div>
        <Button onClick={() => setShowCreateDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          New Prompt
        </Button>
      </div>

      {/* Search */}
      {prompts.length > 0 && (
        <div className="relative mb-6 max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search prompts..."
            className="w-full pl-9 h-9"
          />
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            <p className="text-sm text-muted-foreground">Loading prompts...</p>
          </div>
        </div>
      ) : filteredPrompts.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <BookMarked className="h-10 w-10 text-muted-foreground/30" />
          <div>
            <p className="text-sm font-medium">
              {searchQuery ? "No prompts match your search" : "No prompts saved yet"}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {searchQuery
                ? "Try different keywords"
                : "Save reusable system prompts to quickly load them when creating agents"}
            </p>
          </div>
          {!searchQuery && (
            <Button variant="outline" onClick={() => setShowCreateDialog(true)}>
              <Plus className="h-4 w-4 mr-2" />
              Add your first prompt
            </Button>
          )}
        </div>
      ) : (
        <AnimatedList className="space-y-2">
          {filteredPrompts.map((prompt) => (
            <AnimatedListItem key={prompt.id}>
              <Card
                className="group cursor-pointer hover:border-primary/50 transition-colors"
                onClick={() => setPreviewPrompt(prompt)}
              >
                <CardContent className="flex items-start gap-4 py-3 px-4">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm">{prompt.name}</p>
                    {prompt.description && (
                      <p className="text-xs text-muted-foreground mt-0.5">{prompt.description}</p>
                    )}
                    <p className="text-xs text-muted-foreground/60 mt-1.5 line-clamp-2 font-mono">
                      {prompt.content}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8"
                      onClick={(e) => { e.stopPropagation(); openEditDialog(prompt) }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={(e) => { e.stopPropagation(); handleDelete(prompt.id, prompt.name) }}
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
      <Dialog open={!!previewPrompt} onOpenChange={(o) => { if (!o) setPreviewPrompt(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{previewPrompt?.name}</DialogTitle>
            {previewPrompt?.description && (
              <DialogDescription>{previewPrompt.description}</DialogDescription>
            )}
          </DialogHeader>
          <div className="border rounded-md p-3 bg-muted/30 max-h-96 overflow-y-auto">
            <pre className="text-xs font-mono whitespace-pre-wrap break-words">
              {previewPrompt?.content}
            </pre>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              if (previewPrompt) { openEditDialog(previewPrompt); setPreviewPrompt(null) }
            }}>
              <Pencil className="h-4 w-4 mr-2" />
              Edit
            </Button>
            <Button onClick={() => setPreviewPrompt(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>New Prompt</DialogTitle>
            <DialogDescription>
              Save a reusable system prompt to your vault.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-name">Name</Label>
              <Input
                id="create-name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="e.g., Customer Support Agent"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-desc">Description (Optional)</Label>
              <Input
                id="create-desc"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                placeholder="Brief description of this prompt's purpose"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-content">Prompt Content</Label>
              <Textarea
                id="create-content"
                value={createContent}
                onChange={(e) => setCreateContent(e.target.value)}
                placeholder="You are a helpful AI assistant..."
                rows={10}
                required
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setShowCreateDialog(false)
                  setCreateName("")
                  setCreateDescription("")
                  setCreateContent("")
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
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Prompt</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleEdit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">Name</Label>
              <Input
                id="edit-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Prompt name"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-desc">Description</Label>
              <Input
                id="edit-desc"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="Brief description"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-content">Prompt Content</Label>
              <Textarea
                id="edit-content"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                rows={10}
                required
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => { setShowEditDialog(false); setEditingPrompt(null) }}
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
    </div>
  )
}
