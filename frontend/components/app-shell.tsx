"use client"

import { useEffect, useLayoutEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import { apiClient } from "@/lib/api-client"
import { GetAPIStatus } from "@/app/api/os"
import { usePermissionsStore } from "@/stores/permissions-store"
import { AppSidebar } from "@/components/app-sidebar"
import { Button } from "@/components/ui/button"
import { RefreshCw } from "lucide-react"

export function AppShell({ children }: { children: React.ReactNode }) {
  const { data: session, status, update: updateSession } = useSession()
  const router = useRouter()
  const [serverStatus, setServerStatus] = useState("checking...")
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [tokenReady, setTokenReady] = useState(false)
  const fetchPermissions = usePermissionsStore((s) => s.fetchPermissions)
  const latestRole = usePermissionsStore((s) => s.latestRole)

  useLayoutEffect(() => {
    if (status === "unauthenticated") {
      router.push("/login")
    }
    if (status === "authenticated" && session?.accessToken) {
      apiClient.setAccessToken(session.accessToken)
      setTokenReady(true)
    }
  }, [status, router, session?.accessToken])

  useEffect(() => {
    if (!tokenReady) return
    checkStatus()
    fetchPermissions(session?.accessToken)
  }, [tokenReady])

  // Re-fetch permissions when the window regains focus so that role/permission
  // changes made by an admin in another session are picked up without a reload.
  useEffect(() => {
    if (!tokenReady) return
    const handleFocus = () => {
      fetchPermissions(session?.accessToken)
    }
    window.addEventListener("focus", handleFocus)
    return () => window.removeEventListener("focus", handleFocus)
  }, [tokenReady, session?.accessToken, fetchPermissions])

  // When the DB role (from /get_user_details) differs from the NextAuth session
  // role, update the session so sidebar and route guards reflect the change.
  useEffect(() => {
    const sessionRole = (session?.user as { role?: string })?.role
    if (latestRole && sessionRole && latestRole !== sessionRole) {
      updateSession({ role: latestRole })
    }
  }, [latestRole, session?.user, updateSession])

  const checkStatus = async () => {
    if (!session?.accessToken) return
    const result = await GetAPIStatus(session.accessToken)
    setServerStatus(result?.status ?? "unavailable")
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    await checkStatus()
    await fetchPermissions(session?.accessToken)
    window.dispatchEvent(new CustomEvent("app-refresh"))
    setIsRefreshing(false)
  }

  if (status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  if (status === "unauthenticated") return null

  if (!tokenReady) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-background">
      <AppSidebar />
      <div className="flex-1 flex flex-col min-w-0 min-h-0">
        {/* Top bar */}
        <div className="flex items-center h-12 px-4 border-b border-border justify-between">
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${
                  serverStatus === "ok"
                    ? "bg-emerald-500"
                    : serverStatus === "checking..."
                      ? "bg-muted-foreground animate-pulse"
                      : "bg-amber-500"
                }`}
              />
              <span className="text-xs text-muted-foreground">
                {serverStatus === "ok"
                  ? "Backend Connected"
                  : serverStatus === "checking..."
                    ? "Connecting..."
                    : "Backend Unavailable"}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs gap-1.5"
            onClick={handleRefresh}
            disabled={isRefreshing}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
        {/* Main content */}
        <div className="flex-1 min-h-0 relative">
          <div className="absolute inset-0 flex flex-col">
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
