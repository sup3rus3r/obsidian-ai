"use client"

import { useState, useEffect } from "react"
import { useSession } from "next-auth/react"
import { Settings, Shield, KeyRound, Smartphone, Loader2, Key, Eye, EyeOff, Plus, Trash2, Pencil } from "lucide-react"
import { toast } from "sonner"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Separator } from "@/components/ui/separator"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { apiClient } from "@/lib/api-client"
import { usePermissionsStore } from "@/stores/permissions-store"
import { AppRoutes } from "@/app/api/routes"
import { encryptPayload } from "@/lib/crypto"

export default function SettingsPage() {
  const { data: session, update } = useSession()

  return (
    <div className="h-full w-full overflow-y-auto p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
          <Settings className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Application settings and preferences
          </p>
        </div>
      </div>

      <div className="space-y-6">
        <RoleManagementCard session={session} update={update} />
        <ChangePasswordCard session={session} />
        <TwoFactorCard session={session} />
        <SecretsCard session={session} />
      </div>
    </div>
  )
}


// ============================================================================
// Role Management Card (existing functionality)
// ============================================================================

function RoleManagementCard({ session, update }: { session: any; update: any }) {
  const [toggling, setToggling] = useState(false)
  const fetchPermissions = usePermissionsStore((s) => s.fetchPermissions)

  const userRole = (session?.user as { role?: string })?.role ?? "user"
  const isAdmin = userRole === "admin"

  const handleToggleRole = async () => {
    setToggling(true)
    try {
      const res = await fetch(AppRoutes.ToggleRole(), {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to toggle role" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      const data = await res.json()

      await update({
        role: data.user.role,
        accessToken: data.access_token,
      })

      apiClient.setAccessToken(data.access_token)

      // Re-fetch permissions so the UI (Create Tools, etc.) updates immediately
      await fetchPermissions(data.access_token)

      toast.success(`Role changed to ${data.user.role}`)
    } catch (e: any) {
      toast.error(e.message || "Something went wrong")
    } finally {
      setToggling(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-muted-foreground" />
          <CardTitle>Role Management</CardTitle>
        </div>
        <CardDescription>
          Toggle between admin and user roles. Admin role grants access to the admin panel and management features.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Label htmlFor="admin-toggle" className="text-sm">
              Admin Mode
            </Label>
            <Badge variant={isAdmin ? "default" : "secondary"}>
              {userRole}
            </Badge>
          </div>
          <Switch
            id="admin-toggle"
            checked={isAdmin}
            onCheckedChange={handleToggleRole}
            disabled={toggling}
          />
        </div>
      </CardContent>
    </Card>
  )
}


// ============================================================================
// Change Password Card
// ============================================================================

function ChangePasswordCard({ session }: { session: any }) {
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [loading, setLoading] = useState(false)

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()

    if (newPassword !== confirmPassword) {
      toast.error("New passwords do not match")
      return
    }
    if (newPassword.length < 8) {
      toast.error("Password must be at least 8 characters")
      return
    }

    setLoading(true)
    try {
      const encrypted = encryptPayload({
        current_password: currentPassword,
        new_password: newPassword,
      })

      const res = await fetch(AppRoutes.ChangePassword(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
        body: JSON.stringify({ encrypted }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to change password" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      toast.success("Password changed successfully")
      setCurrentPassword("")
      setNewPassword("")
      setConfirmPassword("")
    } catch (e: any) {
      toast.error(e.message || "Failed to change password")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-muted-foreground" />
          <CardTitle>Change Password</CardTitle>
        </div>
        <CardDescription>
          Update your password. You will need to enter your current password.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleChangePassword} className="space-y-4 max-w-md">
          <div className="space-y-2">
            <Label htmlFor="current-password">Current Password</Label>
            <Input
              id="current-password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password">New Password</Label>
            <Input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Minimum 8 characters"
              required
              minLength={8}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm-password">Confirm New Password</Label>
            <Input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
          </div>
          <Button type="submit" disabled={loading} variant="outline">
            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Change Password
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}


// ============================================================================
// Two-Factor Authentication Card
// ============================================================================

function TwoFactorCard({ session }: { session: any }) {
  const [totpEnabled, setTotpEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [setupData, setSetupData] = useState<{
    qr_code_data_uri: string
    manual_key: string
  } | null>(null)
  const [verifyCode, setVerifyCode] = useState("")
  const [verifying, setVerifying] = useState(false)
  const [showDisableForm, setShowDisableForm] = useState(false)
  const [disablePassword, setDisablePassword] = useState("")
  const [disableCode, setDisableCode] = useState("")
  const [disabling, setDisabling] = useState(false)

  // Fetch 2FA status on mount
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(AppRoutes.TOTPStatus(), {
          headers: { Authorization: `Bearer ${session?.accessToken}` },
        })
        if (res.ok) {
          const data = await res.json()
          setTotpEnabled(data.totp_enabled)
        }
      } finally {
        setLoading(false)
      }
    }
    if (session?.accessToken) fetchStatus()
  }, [session?.accessToken])

  const handleSetup = async () => {
    setLoading(true)
    try {
      const res = await fetch(AppRoutes.TOTPSetup(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to start 2FA setup" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setSetupData(data)
    } catch (e: any) {
      toast.error(e.message || "Failed to initiate 2FA setup")
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    setVerifying(true)
    try {
      const encrypted = encryptPayload({ totp_code: verifyCode })
      const res = await fetch(AppRoutes.TOTPVerify(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
        body: JSON.stringify({ encrypted }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Verification failed" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Two-factor authentication enabled!")
      setTotpEnabled(true)
      setSetupData(null)
      setVerifyCode("")
    } catch (e: any) {
      toast.error(e.message || "Verification failed")
    } finally {
      setVerifying(false)
    }
  }

  const handleDisable = async (e: React.FormEvent) => {
    e.preventDefault()
    setDisabling(true)
    try {
      const encrypted = encryptPayload({
        ...(disablePassword ? { password: disablePassword } : {}),
        ...(disableCode ? { totp_code: disableCode } : {}),
      })
      const res = await fetch(AppRoutes.TOTPDisable(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
        body: JSON.stringify({ encrypted }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to disable 2FA" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      toast.success("Two-factor authentication disabled")
      setTotpEnabled(false)
      setShowDisableForm(false)
      setDisablePassword("")
      setDisableCode("")
    } catch (e: any) {
      toast.error(e.message || "Failed to disable 2FA")
    } finally {
      setDisabling(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Smartphone className="h-4 w-4 text-muted-foreground" />
          <CardTitle>Two-Factor Authentication</CardTitle>
        </div>
        <CardDescription>
          Add an extra layer of security with a TOTP authenticator app.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            <p className="text-sm text-muted-foreground">Loading...</p>
          </div>
        ) : totpEnabled ? (
          /* 2FA is enabled */
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Badge variant="default">Enabled</Badge>
              <span className="text-sm text-muted-foreground">
                Two-factor authentication is active
              </span>
            </div>
            {!showDisableForm ? (
              <Button variant="outline" onClick={() => setShowDisableForm(true)}>
                Disable 2FA
              </Button>
            ) : (
              <form onSubmit={handleDisable} className="space-y-4 max-w-md">
                <p className="text-sm text-muted-foreground">
                  Enter your password or a TOTP code to disable 2FA.
                </p>
                <div className="space-y-2">
                  <Label htmlFor="disable-password">Password</Label>
                  <Input
                    id="disable-password"
                    type="password"
                    value={disablePassword}
                    onChange={(e) => setDisablePassword(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="disable-code">Or TOTP Code</Label>
                  <Input
                    id="disable-code"
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="000000"
                    value={disableCode}
                    onChange={(e) => setDisableCode(e.target.value)}
                  />
                </div>
                <div className="flex gap-2">
                  <Button type="submit" variant="destructive" disabled={disabling}>
                    {disabling && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                    Confirm Disable
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setShowDisableForm(false)
                      setDisablePassword("")
                      setDisableCode("")
                    }}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            )}
          </div>
        ) : setupData ? (
          /* Setup in progress */
          <div className="space-y-4">
            <p className="text-sm">
              Scan this QR code with your authenticator app (Google Authenticator, Authy, etc.)
            </p>
            <div className="flex justify-center p-4 bg-white rounded-lg w-fit">
              <img
                src={setupData.qr_code_data_uri}
                alt="QR Code for 2FA setup"
                className="w-48 h-48"
              />
            </div>
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                Or enter this key manually:
              </p>
              <code className="text-sm font-mono bg-muted px-2 py-1 rounded select-all">
                {setupData.manual_key}
              </code>
            </div>
            <Separator />
            <form onSubmit={handleVerify} className="space-y-4 max-w-md">
              <div className="space-y-2">
                <Label htmlFor="verify-code">
                  Enter the 6-digit code from your authenticator
                </Label>
                <Input
                  id="verify-code"
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="000000"
                  value={verifyCode}
                  onChange={(e) => setVerifyCode(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="flex gap-2">
                <Button type="submit" disabled={verifying}>
                  {verifying && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Verify & Enable
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setSetupData(null)
                    setVerifyCode("")
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </div>
        ) : (
          /* 2FA not enabled */
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <Badge variant="secondary">Disabled</Badge>
              <span className="text-sm text-muted-foreground">
                Two-factor authentication is not enabled
              </span>
            </div>
            <Button variant="outline" onClick={handleSetup}>
              Enable 2FA
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}


// ============================================================================
// Secrets Management Card
// ============================================================================

interface Secret {
  id: string
  name: string
  masked_value: string
  description: string | null
  created_at: string
  updated_at: string | null
}

function SecretsCard({ session }: { session: any }) {
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
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
        body: JSON.stringify({ encrypted }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to create secret" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      toast.success("Secret created successfully")
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
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session?.accessToken}`,
        },
        body: JSON.stringify({ encrypted }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Failed to update secret" }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }

      toast.success("Secret updated successfully")
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
    if (!confirm(`Are you sure you want to delete "${name}"? This cannot be undone.`)) return

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
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Key className="h-4 w-4 text-muted-foreground" />
              <CardTitle>Secrets</CardTitle>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowCreateDialog(true)}
            >
              <Plus className="h-4 w-4 mr-2" />
              Add Secret
            </Button>
          </div>
          <CardDescription>
            Securely store API keys, tokens, and other sensitive values. All secrets are encrypted at rest.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              <p className="text-sm text-muted-foreground">Loading secrets...</p>
            </div>
          ) : secrets.length === 0 ? (
            <p className="text-sm text-muted-foreground">No secrets stored yet.</p>
          ) : (
            <div className="space-y-3 ">
              {secrets.map((secret) => (
                <div
                  key={secret.id}
                  className="flex items-center justify-between p-3 border rounded-lg"
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm">{secret.name}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <code className="text-xs font-mono bg-muted px-2 py-0.5 rounded w-full">
                        {revealedSecrets.has(secret.id) ? secret.masked_value : "***************"}
                      </code>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => toggleReveal(secret.id)}
                      >
                        {revealedSecrets.has(secret.id) ? (
                          <EyeOff className="h-3 w-3" />
                        ) : (
                          <Eye className="h-3 w-3" />
                        )}
                      </Button>
                    </div>
                    {secret.description && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {secret.description}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 ml-3">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0"
                      onClick={() => openEditDialog(secret)}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                      onClick={() => handleDelete(secret.id, secret.name)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Create Secret Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add New Secret</DialogTitle>
            <DialogDescription>
              Store a new encrypted secret. Data is encrypted in transit and at rest.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="create-secret-name">Name</Label>
              <Input
                id="create-secret-name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="e.g., OpenAI API Key"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-secret-value">Secret Value</Label>
              <Input
                id="create-secret-value"
                type="password"
                value={createValue}
                onChange={(e) => setCreateValue(e.target.value)}
                placeholder="Enter secret value"
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="create-secret-desc">Description (Optional)</Label>
              <Textarea
                id="create-secret-desc"
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

      {/* Edit Secret Dialog */}
      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent className="min-w-200">
          <DialogHeader>
            <DialogTitle>Edit Secret</DialogTitle>
            <DialogDescription>
              Update the secret. Leave value empty to keep the existing value.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEdit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-secret-name">Name</Label>
              <Input
                id="edit-secret-name"
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder="Secret name"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-secret-value">New Secret Value (Optional)</Label>
              <Input
                id="edit-secret-value"
                type="password"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                placeholder="Leave empty to keep existing"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-secret-desc">Description</Label>
              <Textarea
                id="edit-secret-desc"
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
                onClick={() => {
                  setShowEditDialog(false)
                  setEditingSecret(null)
                }}
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
    </>
  )
}
