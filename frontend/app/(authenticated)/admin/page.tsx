"use client"

import { useEffect, useLayoutEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import { Routes, hasAccess } from "@/config/routes"
import { useAdminStore } from "@/stores/admin-store"
import { useConfirm } from "@/hooks/use-confirm"
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { CreateUserDialog } from "@/components/dialogs/create-user-dialog"
import { EditPermissionsDialog } from "@/components/dialogs/edit-permissions-dialog"
import { Shield, Plus, Trash2, Settings, Users } from "lucide-react"
import type { AdminUser, UserPermissions } from "@/types/playground"

export default function AdminPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const userRole = (session?.user as { role?: string })?.role ?? "user"
  const { users, isLoading, fetchUsers, deleteUser } = useAdminStore()

  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [editUser, setEditUser] = useState<AdminUser | null>(null)
  const [editDialogOpen, setEditDialogOpen] = useState(false)

  const [ConfirmDelete, confirmDelete] = useConfirm({
    title: "Delete user",
    description:
      "This will permanently delete this user and cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  useLayoutEffect(() => {
    if (status === "unauthenticated") router.push(Routes.LOGIN)
    if (status === "authenticated" && !hasAccess(userRole, ["admin"]))
      router.push(Routes.DASHBOARD)
  }, [status, router, userRole])

  useEffect(() => {
    if (status === "authenticated" && hasAccess(userRole, ["admin"])) {
      fetchUsers()
    }
  }, [status, userRole, fetchUsers])

  // Listen for app-refresh events
  useEffect(() => {
    const handler = () => fetchUsers()
    window.addEventListener("app-refresh", handler)
    return () => window.removeEventListener("app-refresh", handler)
  }, [fetchUsers])

  const handleDelete = async (user: AdminUser) => {
    const ok = await confirmDelete()
    if (!ok) return
    try {
      await deleteUser(user.id)
    } catch {}
  }

  const handleEdit = (user: AdminUser) => {
    setEditUser(user)
    setEditDialogOpen(true)
  }

  const enabledCount = (perms: UserPermissions) =>
    Object.values(perms).filter(Boolean).length

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (!hasAccess(userRole, ["admin"])) return null

  return (
    <div className="h-full overflow-y-auto p-6 w-full mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-10 w-10 rounded-xl bg-muted">
            <Shield className="h-5 w-5 text-muted-foreground" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Admin Panel</h1>
            <p className="text-sm text-muted-foreground">
              Manage users and permissions
            </p>
          </div>
        </div>
        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Create User
        </Button>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Users className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-2xl font-bold">{users.length}</p>
                <p className="text-xs text-muted-foreground">Total Users</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Shield className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-2xl font-bold">
                  {users.filter((u) => u.role === "admin").length}
                </p>
                <p className="text-xs text-muted-foreground">Admins</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <Users className="h-5 w-5 text-muted-foreground" />
              <div>
                <p className="text-2xl font-bold">
                  {users.filter((u) => u.role === "user").length}
                </p>
                <p className="text-xs text-muted-foreground">Users</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Users Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">All Users</CardTitle>
          <CardDescription>
            Manage user accounts, roles, and resource permissions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
            </div>
          ) : (
            <div className="rounded-md border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                      Username
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                      Email
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                      Role
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                      Permissions
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-muted-foreground">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr
                      key={user.id}
                      className="border-b last:border-b-0 hover:bg-muted/30 transition-colors"
                    >
                      <td className="px-4 py-3 font-medium">{user.username}</td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {user.email}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant={
                            user.role === "admin" ? "default" : "secondary"
                          }
                        >
                          {user.role}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-muted-foreground">
                          {enabledCount(user.permissions)}/{Object.keys(user.permissions).length} enabled
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleEdit(user)}
                          >
                            <Settings className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={() => handleDelete(user)}
                            disabled={user.id === session?.user?.id}
                          >
                            <Trash2 className="h-3.5 w-3.5 text-destructive" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {users.length === 0 && (
                    <tr>
                      <td
                        colSpan={5}
                        className="px-4 py-8 text-center text-muted-foreground"
                      >
                        No users found.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Dialogs */}
      <CreateUserDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
      />
      <EditPermissionsDialog
        open={editDialogOpen}
        onOpenChange={(o) => {
          setEditDialogOpen(o)
          if (!o) setEditUser(null)
        }}
        user={editUser}
      />
      <ConfirmDelete />
    </div>
  )
}
