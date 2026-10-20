"use client"

import { useState, useEffect } from "react"
import { useSession } from "next-auth/react"
import { Key, Plus, Trash2, Pencil, Loader2, Info, CreditCard, LogIn, Users, CheckCircle2, Circle, Eye, EyeOff, Copy, Check } from "lucide-react"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { AnimatedList, AnimatedListItem } from "@/components/ui/animated-list"
import { AppRoutes } from "@/app/api/routes"
import { encryptPayload } from "@/lib/crypto"
import { apiClient } from "@/lib/api-client"
import { useConfirm } from "@/hooks/use-confirm"
import type { Secret, SecretType, Agent } from "@/types/playground"
import { SECRET_TYPE_SCHEMAS } from "@/types/playground"

const SECRET_TYPE_OPTIONS: { value: SecretType; label: string; icon: React.ElementType }[] = [
  { value: "generic", label: "Generic", icon: Key },
  { value: "credit_card", label: "Credit Card", icon: CreditCard },
  { value: "login", label: "Login", icon: LogIn },
]

function typeIcon(type: SecretType) {
  return SECRET_TYPE_OPTIONS.find((o) => o.value === type)?.icon ?? Key
}

function typeLabel(type: SecretType) {
  return SECRET_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? "Generic"
}

export default function SecretsPage() {
  const { data: session } = useSession()
  const [secrets, setSecrets] = useState<Secret[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [editingSecret, setEditingSecret] = useState<Secret | null>(null)
  const [revealedValues, setRevealedValues] = useState<Record<string, Record<string, string>>>({})
  const [revealingId, setRevealingId] = useState<string | null>(null)
  const [copiedField, setCopiedField] = useState<string | null>(null)
  const [ConfirmDeleteDialog, confirmDelete] = useConfirm({
    title: "Delete secret",
    description: "This will permanently delete this secret. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  // Create form state
  const [createName, setCreateName] = useState("")
  const [createType, setCreateType] = useState<SecretType>("generic")
  const [createFields, setCreateFields] = useState<Record<string, string>>({ value: "" })
  const [createDescription, setCreateDescription] = useState("")
  const [creating, setCreating] = useState(false)

  // Edit form state
  const [editName, setEditName] = useState("")
  const [editFields, setEditFields] = useState<Record<string, string>>({})
  const [editDescription, setEditDescription] = useState("")
  const [editing, setEditing] = useState(false)

  // Agent access dialog state
  const [showAccessDialog, setShowAccessDialog] = useState(false)
  const [accessSecret, setAccessSecret] = useState<Secret | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [accessAgentIds, setAccessAgentIds] = useState<string[]>([])
  const [loadingAccess, setLoadingAccess] = useState(false)
  const [savingAccess, setSavingAccess] = useState(false)

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

  const resetCreateForm = () => {
    setCreateName("")
    setCreateType("generic")
    setCreateFields({ value: "" })
    setCreateDescription("")
  }

  const handleCreateTypeChange = (type: SecretType) => {
    setCreateType(type)
    const blank: Record<string, string> = {}
    for (const field of Object.keys(SECRET_TYPE_SCHEMAS[type])) blank[field] = ""
    setCreateFields(blank)
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    const schema = SECRET_TYPE_SCHEMAS[createType]
    const missing = Object.keys(schema).some((f) => !createFields[f]?.trim())
    if (!createName.trim() || missing) {
      toast.error("Name and all fields are required")
      return
    }
    setCreating(true)
    try {
      const encrypted = encryptPayload({
        name: createName.trim(),
        secret_type: createType,
        fields: createFields,
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
      resetCreateForm()
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
    const schema = SECRET_TYPE_SCHEMAS[editingSecret.secret_type]
    const missing = Object.keys(schema).some((f) => !editFields[f]?.trim())
    if (missing) {
      toast.error("All fields are required when editing — re-enter sensitive fields to save changes")
      return
    }
    const updates: Record<string, any> = { fields: editFields, secret_type: editingSecret.secret_type }
    if (editName.trim() && editName.trim() !== editingSecret.name) updates.name = editName.trim()
    if (editDescription !== (editingSecret.description || "")) updates.description = editDescription.trim() || null

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
    const ok = await confirmDelete()
    if (!ok) return
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

  const openEditDialog = (secret: Secret) => {
    setEditingSecret(secret)
    setEditName(secret.name)
    const schema = SECRET_TYPE_SCHEMAS[secret.secret_type]
    const prefilled: Record<string, string> = {}
    for (const [field, meta] of Object.entries(schema)) {
      prefilled[field] = meta.sensitive ? "" : (secret.fields[field] || "")
    }
    setEditFields(prefilled)
    setEditDescription(secret.description || "")
    setShowEditDialog(true)
  }

  const openAccessDialog = async (secret: Secret) => {
    setAccessSecret(secret)
    setShowAccessDialog(true)
    setLoadingAccess(true)
    try {
      const [fetchedAgents, access] = await Promise.all([
        apiClient.listAgents(),
        apiClient.getSecretAccess(secret.id),
      ])
      setAgents(fetchedAgents)
      setAccessAgentIds(access.agent_ids)
    } catch (e: any) {
      toast.error(e.message || "Failed to load agent access")
    } finally {
      setLoadingAccess(false)
    }
  }

  const toggleAccessAgent = (agentId: string) => {
    setAccessAgentIds((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId],
    )
  }

  const handleSaveAccess = async () => {
    if (!accessSecret) return
    setSavingAccess(true)
    try {
      await apiClient.setSecretAccess(accessSecret.id, accessAgentIds)
      toast.success("Agent access updated")
      setShowAccessDialog(false)
      setAccessSecret(null)
    } catch (e: any) {
      toast.error(e.message || "Failed to update agent access")
    } finally {
      setSavingAccess(false)
    }
  }

  const nonSensitiveSummary = (secret: Secret): string | null => {
    const schema = SECRET_TYPE_SCHEMAS[secret.secret_type]
    const parts = Object.entries(schema)
      .filter(([, meta]) => !meta.sensitive)
      .map(([field, meta]) => `${meta.label}: ${secret.fields[field] || "—"}`)
    return parts.length > 0 ? parts.join(" · ") : null
  }

  const MASK_DISPLAY_LENGTH = 28

  // The backend only ever sends a short "***" hint for sensitive fields —
  // use a fixed-width dot run instead so the row fills the card instead of
  // collapsing to 3 characters.
  const maskedValuePreview = "•".repeat(MASK_DISPLAY_LENGTH)

  const toggleReveal = async (secret: Secret) => {
    if (revealedValues[secret.id]) {
      setRevealedValues((prev) => {
        const next = { ...prev }
        delete next[secret.id]
        return next
      })
      return
    }
    setRevealingId(secret.id)
    try {
      const { fields } = await apiClient.revealSecret(secret.id)
      setRevealedValues((prev) => ({ ...prev, [secret.id]: fields }))
    } catch {
      toast.error("Failed to reveal secret")
    } finally {
      setRevealingId(null)
    }
  }

  const copyValue = async (secretId: string, field: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopiedField(`${secretId}:${field}`)
      setTimeout(() => setCopiedField(null), 1500)
    } catch {
      toast.error("Failed to copy")
    }
  }

  return (
    <div className="h-full overflow-y-auto p-8 w-full space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
            <Key className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-medium tracking-[-0.016em]">Secrets Vault</h1>
              <Badge variant="secondary">{secrets.length}</Badge>
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

      {/* Help callout */}
      <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 p-4">
        <Info className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
        <div className="text-sm text-muted-foreground space-y-1">
          <p>
            Reference a vaulted secret in tool calls, sandbox commands, or chat replies with{" "}
            <code className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">{"{{secrets.<name>.<field>}}"}</code>{" "}
            (generic secrets omit the field, e.g.{" "}
            <code className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">{"{{secrets.my_api_key}}"}</code>).
          </p>
          <p>
            The placeholder is resolved server-side at execution time — the real value is never sent to the LLM.
            A secret only resolves for agents explicitly granted access; use the{" "}
            <Users className="h-3 w-3 inline -mt-0.5" /> button on a secret to manage which agents can use it.
          </p>
        </div>
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
          <Key className="h-10 w-10 text-muted-foreground" />
          <div>
            <p className="text-base font-medium">No secrets stored yet</p>
            <p className="text-sm text-muted-foreground mt-1">
              Add API keys, tokens, and other sensitive values to use in your agents
            </p>
          </div>
          <Button variant="outline" onClick={() => setShowCreateDialog(true)}>
            <Plus className="h-4 w-4 mr-2" />
            Add your first secret
          </Button>
        </div>
      ) : (
        <AnimatedList className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 items-start">
          {secrets.map((secret) => {
            const TypeIcon = typeIcon(secret.secret_type)
            return (
              <AnimatedListItem key={secret.id} className="h-full">
                <Card className="group h-full flex flex-col shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 hover:border-primary/40">
                  <CardContent className="px-4 py-4 flex-1 flex flex-col">
                    <div className="flex items-start gap-3 flex-1">
                      <div className="h-9 w-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                        <TypeIcon className="h-4 w-4 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0 flex flex-col">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <p className="font-medium text-sm truncate">{secret.name}</p>
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0">
                              {typeLabel(secret.secret_type)}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              className="h-7 w-7"
                              onClick={() => openAccessDialog(secret)}
                              title="Manage agent access"
                            >
                              <Users className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              className="h-7 w-7"
                              onClick={() => openEditDialog(secret)}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              onClick={() => handleDelete(secret.id, secret.name)}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1 min-h-4">
                          {secret.description || " "}
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1 min-h-4">
                          {nonSensitiveSummary(secret) || " "}
                        </p>
                        <div className="flex-1" />
                        <div className="flex flex-col gap-1.5 mt-2">
                          {revealedValues[secret.id] ? (
                            Object.entries(SECRET_TYPE_SCHEMAS[secret.secret_type])
                              .filter(([, meta]) => meta.sensitive)
                              .map(([field, meta]) => {
                                const value = revealedValues[secret.id][field] || ""
                                const copyKey = `${secret.id}:${field}`
                                return (
                                  <div key={field} className="flex items-center gap-1.5">
                                    <code className="text-xs font-mono bg-muted px-2 py-1 rounded truncate flex-1" title={meta.label}>
                                      {value}
                                    </code>
                                    <Button
                                      variant="ghost"
                                      size="icon-sm"
                                      className="h-6 w-6 shrink-0"
                                      onClick={() => copyValue(secret.id, field, value)}
                                      title={`Copy ${meta.label}`}
                                    >
                                      {copiedField === copyKey ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
                                    </Button>
                                  </div>
                                )
                              })
                          ) : (
                            <code className="block text-xs font-mono bg-muted px-2 py-1 rounded truncate">
                              {maskedValuePreview}
                            </code>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 self-start px-1.5 text-xs text-muted-foreground"
                            onClick={() => toggleReveal(secret)}
                            disabled={revealingId === secret.id}
                          >
                            {revealingId === secret.id
                              ? <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                              : revealedValues[secret.id] ? <EyeOff className="h-3 w-3 mr-1" /> : <Eye className="h-3 w-3 mr-1" />}
                            {revealedValues[secret.id] ? "Hide" : "Reveal"}
                          </Button>
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </AnimatedListItem>
            )
          })}
        </AnimatedList>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={(o) => { setShowCreateDialog(o); if (!o) resetCreateForm() }}>
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
              <Label htmlFor="create-type">Type</Label>
              <Select value={createType} onValueChange={(v) => handleCreateTypeChange(v as SecretType)}>
                <SelectTrigger id="create-type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SECRET_TYPE_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {Object.entries(SECRET_TYPE_SCHEMAS[createType]).map(([field, meta]) => (
              <div className="space-y-2" key={field}>
                <Label htmlFor={`create-field-${field}`}>{meta.label}</Label>
                <Input
                  id={`create-field-${field}`}
                  type={meta.sensitive ? "password" : "text"}
                  value={createFields[field] || ""}
                  onChange={(e) => setCreateFields((prev) => ({ ...prev, [field]: e.target.value }))}
                  placeholder={meta.label}
                  required
                />
              </div>
            ))}
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
                  resetCreateForm()
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
              Sensitive fields are never returned by the API in the clear, so they must be re-entered to save any
              change to this secret.
            </DialogDescription>
          </DialogHeader>
          {editingSecret && (
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
              {Object.entries(SECRET_TYPE_SCHEMAS[editingSecret.secret_type]).map(([field, meta]) => (
                <div className="space-y-2" key={field}>
                  <Label htmlFor={`edit-field-${field}`}>{meta.label}</Label>
                  <Input
                    id={`edit-field-${field}`}
                    type={meta.sensitive ? "password" : "text"}
                    value={editFields[field] || ""}
                    onChange={(e) => setEditFields((prev) => ({ ...prev, [field]: e.target.value }))}
                    placeholder={meta.sensitive ? "Re-enter to keep this secret valid" : meta.label}
                    required
                  />
                </div>
              ))}
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
          )}
        </DialogContent>
      </Dialog>

      {/* Agent Access Dialog */}
      <Dialog open={showAccessDialog} onOpenChange={setShowAccessDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Agent Access</DialogTitle>
            <DialogDescription>
              {accessSecret ? `Choose which agents can resolve {{secrets.${accessSecret.name}...}} placeholders.` : ""}
            </DialogDescription>
          </DialogHeader>
          {loadingAccess ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : agents.length === 0 ? (
            <p className="text-xs text-muted-foreground">No agents available yet.</p>
          ) : (
            <div className="space-y-1 max-h-60 overflow-y-auto rounded-md border border-border p-2">
              {agents.map((agent) => {
                const isEnabled = accessAgentIds.includes(agent.id)
                return (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => toggleAccessAgent(agent.id)}
                    className="w-full flex items-start gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                  >
                    <div className="pt-0.5">
                      {isEnabled ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                      ) : (
                        <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="font-medium">{agent.name}</div>
                    </div>
                  </button>
                )
              })}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAccessDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveAccess} disabled={savingAccess || loadingAccess}>
              {savingAccess && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save Access
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDeleteDialog />
    </div>
  )
}
