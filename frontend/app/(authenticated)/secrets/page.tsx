"use client"

import { useState, useEffect } from "react"
import { useSession } from "next-auth/react"
import { Key, Plus, Trash2, Pencil, Eye, EyeOff, Loader2 } from "lucide-react"
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
import { encryptPayload } from "@/lib/crypto"

interface Secret {
  id: string
  name: string
  masked_value: string
  description: string | null
  created_at: string
  updated_at: string | null
}

export default function SecretsPage() {
  const { data: session } = useSession()
  const [secrets, setSecrets] = useState<Secret[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [editingSecret, setEditingSecret] = useState<Secret | null>(null)
  const [revealedSecrets, setRevealedSecrets] = useState<Set<string>>(new Set())

  // Create form state
  const [createName, setCreateName] = useState("")
  const [createValue, setCreateValue] = useState("")
  const [createDescription, setCreateDescription] = useState("")
  const [creating, setCreating] = useState(false)

  // Edit form state
  const [editName, setEditName] = useState("")
  const [editValue, setEditValue] = useState("")
  const [editDescription, setEditDescription] = useState("")
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (session?.accessToken) fetchSecrets()
  }, [session?.accessToken])

  const fetchSecrets = async () => {
    setLoading(true)
    try {
      const res = await fetch(AppRoutes.ListSecrets(), {
        headers: { Authorization: `Bearer ${session?.accessToken}` },
      })
      if (res.ok) {
        const data = await res.json()
        setSecrets(data.secrets || [])
      }
    } catch (e) {
      console.error("Failed to fetch secrets:", e)
    } finally {
      setLoading(false)
    }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!createName.trim() || !createValue) {
      toast.error("Name and value are required")
      return
    }
    setCreating(true)
    try {
      const encrypted = encryptPayload({
        name: createName.trim(),
        value: createValue,
        description: createDescription.trim() || null,
      })
      const res = await fetch(AppRoutes.CreateSecret(), {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.accessToken}` },
        body: JSON.stringify({ encrypted }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to create secret" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Secret created")
      setShowCreateDialog(false)
      setCreateName("")
      setCreateValue("")
      setCreateDescription("")
      await fetchSecrets()
    } catch (e: any) {
      toast.error(e.message || "Failed to create secret")
    } finally {
      setCreating(false)
    }
  }

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingSecret) return
    const updates: Record<string, any> = {}
    if (editName.trim() && editName.trim() !== editingSecret.name) updates.name = editName.trim()
    if (editValue) updates.value = editValue
    if (editDescription !== (editingSecret.description || "")) updates.description = editDescription.trim() || null
    if (Object.keys(updates).length === 0) {
      toast.error("No changes to save")
      return
    }
    setEditing(true)
    try {
      const encrypted = encryptPayload(updates)
      const res = await fetch(AppRoutes.UpdateSecret(editingSecret.id), {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${session?.accessToken}` },
        body: JSON.stringify({ encrypted }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to update secret" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Secret updated")
      setShowEditDialog(false)
      setEditingSecret(null)
      await fetchSecrets()
    } catch (e: any) {
      toast.error(e.message || "Failed to update secret")
    } finally {
      setEditing(false)
    }
  }

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return
    try {
      const res = await fetch(AppRoutes.DeleteSecret(id), {
        method: "DELETE",
        headers: { Authorization: `Bearer ${session?.accessToken}` },
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to delete secret" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Secret deleted")
      await fetchSecrets()
    } catch (e: any) {
      toast.error(e.message || "Failed to delete secret")
    }
  }

  const toggleReveal = (id: string) => {
    setRevealedSecrets((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const openEditDialog = (secret: Secret) => {
    setEditingSecret(secret)
    setEditName(secret.name)
    setEditValue("")
    setEditDescription(secret.description || "")
    setShowEditDialog(true)
  }

  return (
    <div className="h-full w-full overflow-y-auto p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
            <Key className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight">Secrets Vault</h1>
              <Badge variant="secondary" className="text-xs">{secrets.length}</Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              Encrypted API keys, tokens, and sensitive values
            </p>
          </div>
        </div>
        <Button onClick={() => setShowCreateDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add Secret
        </Button>
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="flex flex-col items-center gap-3">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            <p className="text-sm text-muted-foreground">Loading secrets...</p>
          </div>
        </div>
      ) : secrets.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <Key className="h-10 w-10 text-muted-foreground/30" />
          <div>
            <p className="text-sm font-medium">No secrets stored yet</p>
            <p className="text-xs text-muted-foreground mt-1">
              Add API keys, tokens, and other sensitive values to use in your agents
            </p>
          </div>
          <Button variant="outline" onClick={() => setShowCreateDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add your first secret
          </Button>
        </div>
      ) : (
        <AnimatedList className="space-y-2">
          {secrets.map((secret) => (
            <AnimatedListItem key={secret.id}>
              <Card className="group">
                <CardContent className="flex items-center gap-4 py-3 px-4">
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm">{secret.name}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <code className="text-xs font-mono bg-muted px-2 py-0.5 rounded">
                        {revealedSecrets.has(secret.id) ? secret.masked_value : "•••••••••••••••"}
                      </code>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => toggleReveal(secret.id)}
                      >
                        {revealedSecrets.has(secret.id)
                          ? <EyeOff className="h-3 w-3" />
                          : <Eye className="h-3 w-3" />}
                      </Button>
                    </div>
                    {secret.description && (
                      <p className="text-xs text-muted-foreground mt-1">{secret.description}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8"
                      onClick={() => openEditDialog(secret)}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={() => handleDelete(secret.id, secret.name)}
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

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Secret</DialogTitle>
            <DialogDescription>
              Encrypted in transit and at rest.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-name">Name</Label>
              <Input
                id="create-name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="e.g., OPENAI_API_KEY"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-value">Secret Value</Label>
              <Input
                id="create-value"
                type="password"
                value={createValue}
                onChange={(e) => setCreateValue(e.target.value)}
                placeholder="Enter secret value"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-desc">Description (Optional)</Label>
              <Textarea
                id="create-desc"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                placeholder="What is this secret for?"
                rows={2}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setShowCreateDialog(false)
                  setCreateName("")
                  setCreateValue("")
                  setCreateDescription("")
                }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={creating}>
                {creating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create Secret
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Secret</DialogTitle>
            <DialogDescription>
              Leave value empty to keep the existing value.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEdit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">Name</Label>
              <Input
                id="edit-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Secret name"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-value">New Value (Optional)</Label>
              <Input
                id="edit-value"
                type="password"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                placeholder="Leave empty to keep existing"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-desc">Description</Label>
              <Textarea
                id="edit-desc"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="What is this secret for?"
                rows={2}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => { setShowEditDialog(false); setEditingSecret(null) }}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={editing}>
                {editing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Update Secret
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
