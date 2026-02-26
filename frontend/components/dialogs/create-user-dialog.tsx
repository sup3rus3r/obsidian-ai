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
import { DEFAULT_PERMISSIONS, PERMISSION_LABELS } from "@/types/playground"
import type { UserPermissions } from "@/types/playground"

interface CreateUserDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreateUserDialog({ open, onOpenChange }: CreateUserDialogProps) {
  const createUser = useAdminStore((s) => s.createUser)
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState("user")
  const [permissions, setPermissions] = useState<UserPermissions>({
    ...DEFAULT_PERMISSIONS,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const handleCreate = async () => {
    if (!username || !email || !password) return
    setError("")
    setLoading(true)
    try {
      await createUser({ username, email, password, role, permissions })
      resetAndClose()
    } catch (err: any) {
      setError(err.message || "Failed to create user")
    } finally {
      setLoading(false)
    }
  }

  const resetAndClose = () => {
    setUsername("")
    setEmail("")
    setPassword("")
    setRole("user")
    setPermissions({ ...DEFAULT_PERMISSIONS })
    setError("")
    onOpenChange(false)
  }

  const togglePermission = (key: keyof UserPermissions) => {
    setPermissions((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) resetAndClose()
        else onOpenChange(o)
      }}
    >
      <DialogContent className="sm:max-w-lg min-w-200">
        <DialogHeader>
          <DialogTitle>Create User</DialogTitle>
          <DialogDescription>
            Add a new user account with custom permissions.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="grid gap-1.5">
              <Label>Username</Label>
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="username"
              />
            </div>
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
          </div>

          <div className="grid gap-1.5">
            <Label>Email</Label>
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@example.com"
            />
          </div>

          <div className="grid gap-1.5">
            <Label>Password</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
            />
          </div>

          <div className="grid gap-2 pt-2">
            <Label className="text-sm font-medium">Permissions</Label>
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
          <Button
            onClick={handleCreate}
            disabled={loading || !username || !email || !password}
          >
            {loading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            Create User
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
