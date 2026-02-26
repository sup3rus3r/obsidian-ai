"use client"

import { useState, useEffect } from "react"
import { useSession } from "next-auth/react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Loader2 } from "lucide-react"
import { useAdminStore } from "@/stores/admin-store"
import { usePermissionsStore } from "@/stores/permissions-store"
import { PERMISSION_LABELS } from "@/types/playground"
import type { AdminUser, UserPermissions } from "@/types/playground"

interface EditPermissionsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: AdminUser | null
}

export function EditPermissionsDialog({
  open,
  onOpenChange,
  user,
}: EditPermissionsDialogProps) {
  const { data: session, update: updateSession } = useSession()
  const updateUser = useAdminStore((s) => s.updateUser)
  const fetchPermissions = usePermissionsStore((s) => s.fetchPermissions)
  const [role, setRole] = useState("")
  const [permissions, setPermissions] = useState<UserPermissions | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (user) {
      setRole(user.role)
      setPermissions({ ...user.permissions })
      setError("")
    }
  }, [user])

  if (!user || !permissions) return null

  const togglePermission = (key: keyof UserPermissions) => {
    setPermissions((prev) =>
      prev ? { ...prev, [key]: !prev[key] } : prev
    )
  }

  const handleSave = async () => {
    setError("")
    setLoading(true)
    try {
      await updateUser(user.id, { role, permissions })

      // If the edited user is the currently logged-in user, refresh their
      // permissions store and NextAuth session so the UI updates immediately.
      const currentUserId = session?.user?.id
      if (currentUserId && String(currentUserId) === String(user.id)) {
        await fetchPermissions(session?.accessToken)
        await updateSession({ role })
      }

      onOpenChange(false)
    } catch (err: any) {
      setError(err.message || "Failed to update user")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md min-w-200">
        <DialogHeader>
          <DialogTitle className="uppercase">Edit User: {user.username}</DialogTitle>
          <DialogDescription>
            Manage role and resource permissions for this user.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid gap-1.5">
            <Label>Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label className="text-sm font-medium">Resource Permissions</Label>
            <div className="rounded-md border p-3 space-y-3">
              {(
                Object.keys(PERMISSION_LABELS) as (keyof UserPermissions)[]
              ).map((key) => (
                <div key={key} className="flex items-center justify-between">
                  <Label className="text-sm text-muted-foreground font-normal">
                    {PERMISSION_LABELS[key]}
                  </Label>
                  <Switch
                    size="sm"
                    checked={permissions[key]}
                    onCheckedChange={() => togglePermission(key)}
                  />
                </div>
              ))}
            </div>
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={loading}>
            {loading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
