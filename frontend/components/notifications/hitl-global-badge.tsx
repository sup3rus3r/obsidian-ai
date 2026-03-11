"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import { apiClient } from "@/lib/api-client"
import type { HITLApprovalItem } from "@/types/playground"
import { AppRoutes } from "@/app/api/routes"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Bell, CheckCircle, XCircle, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const POLL_INTERVAL = 5000

export function HITLGlobalBadge() {
  const { data: authSession } = useSession()
  const router = useRouter()
  const [approvals, setApprovals] = useState<HITLApprovalItem[]>([])
  const [open, setOpen] = useState(false)
  const [actioning, setActioning] = useState<Record<string, boolean>>({})
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!authSession?.accessToken) return
    apiClient.setAccessToken(authSession.accessToken as string)
    poll()
    intervalRef.current = setInterval(poll, POLL_INTERVAL)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [authSession?.accessToken])

  const poll = async () => {
    try {
      const pending = await apiClient.getGlobalPendingHITL()
      setApprovals(pending)
    } catch {
      // silent — badge just stays empty on error
    }
  }

  const handleApprove = async (approval: HITLApprovalItem) => {
    setActioning((prev) => ({ ...prev, [approval.approval_id]: true }))
    try {
      await fetch(AppRoutes.HITLApprove(approval.session_id, approval.approval_id), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${authSession?.accessToken}`,
          "Content-Type": "application/json",
        },
      })
      setApprovals((prev) => prev.filter((a) => a.approval_id !== approval.approval_id))
      toast.success(`Approved: ${approval.tool_name}`)
    } catch {
      toast.error("Failed to approve")
    } finally {
      setActioning((prev) => ({ ...prev, [approval.approval_id]: false }))
    }
  }

  const handleReject = async (approval: HITLApprovalItem) => {
    setActioning((prev) => ({ ...prev, [approval.approval_id]: true }))
    try {
      await fetch(AppRoutes.HITLReject(approval.session_id, approval.approval_id), {
        method: "POST",
        headers: {
          Authorization: `Bearer ${authSession?.accessToken}`,
          "Content-Type": "application/json",
        },
      })
      setApprovals((prev) => prev.filter((a) => a.approval_id !== approval.approval_id))
      toast.success(`Rejected: ${approval.tool_name}`)
    } catch {
      toast.error("Failed to reject")
    } finally {
      setActioning((prev) => ({ ...prev, [approval.approval_id]: false }))
    }
  }

  if (approvals.length === 0) return null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="relative h-8 gap-1.5 text-xs text-amber-600 dark:text-amber-400 hover:bg-amber-500/10"
        >
          <Bell className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Approvals</span>
          <Badge className="absolute -top-1 -right-1 h-4 min-w-4 px-1 text-[10px] bg-amber-500 text-white border-0">
            {approvals.length}
          </Badge>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="px-3 py-2 border-b">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Pending Approvals</p>
        </div>
        <div className="max-h-72 overflow-y-auto divide-y">
          {approvals.map((approval) => (
            <div key={approval.approval_id} className="px-3 py-2.5 space-y-1.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium truncate">{approval.tool_name}</p>
                  <button
                    className="text-xs text-muted-foreground hover:text-foreground truncate block max-w-full text-left"
                    onClick={() => {
                      setOpen(false)
                      router.push(`/sessions?highlight=${approval.session_id}`)
                    }}
                  >
                    Session {approval.session_id.slice(0, 8)}…
                  </button>
                </div>
              </div>
              {approval.tool_arguments && Object.keys(approval.tool_arguments).length > 0 && (
                <pre className="text-[10px] bg-muted rounded p-1.5 overflow-x-auto max-h-20 text-muted-foreground">
                  {JSON.stringify(approval.tool_arguments, null, 2)}
                </pre>
              )}
              <div className="flex gap-1.5">
                <Button
                  size="sm"
                  className="h-6 text-xs flex-1 gap-1"
                  onClick={() => handleApprove(approval)}
                  disabled={actioning[approval.approval_id]}
                >
                  {actioning[approval.approval_id]
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <CheckCircle className="h-3 w-3" />
                  }
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-6 text-xs flex-1 gap-1 text-destructive hover:text-destructive"
                  onClick={() => handleReject(approval)}
                  disabled={actioning[approval.approval_id]}
                >
                  {actioning[approval.approval_id]
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : <XCircle className="h-3 w-3" />
                  }
                  Reject
                </Button>
              </div>
            </div>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
