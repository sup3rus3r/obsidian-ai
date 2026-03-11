"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { apiClient } from "@/lib/api-client"
import type { WAChannel, Agent, CreateWAChannelRequest } from "@/types/playground"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
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
import { MessageCircle, Plus, Trash2, Settings2, Loader2, Wifi, WifiOff, QrCode } from "lucide-react"
import { toast } from "sonner"
import { useConfirm } from "@/hooks/use-confirm"

function StatusBadge({ status }: { status: WAChannel["status"] }) {
  if (status === "connected") return <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30">Connected</Badge>
  if (status === "pending_qr") return <Badge className="bg-amber-500/15 text-amber-600 border-amber-500/30">Scan QR</Badge>
  return <Badge variant="secondary">Disconnected</Badge>
}

export default function ChannelsPage() {
  const { data: authSession } = useSession()
  const router = useRouter()
  const [channels, setChannels] = useState<WAChannel[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState("")
  const [createAgentId, setCreateAgentId] = useState("")
  const [createLoading, setCreateLoading] = useState(false)

  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: "Delete channel",
    description: "This will disconnect and permanently delete this WhatsApp channel. Sessions created via this channel will be kept.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  useEffect(() => {
    if (!authSession?.accessToken) return
    apiClient.setAccessToken(authSession.accessToken as string)
    load()
  }, [authSession?.accessToken])

  const load = async () => {
    setIsLoading(true)
    try {
      const [chs, ags] = await Promise.all([
        apiClient.listWAChannels(),
        apiClient.listAgents(),
      ])
      setChannels(chs)
      setAgents(ags)
    } catch {
      toast.error("Failed to load channels")
    } finally {
      setIsLoading(false)
    }
  }

  const handleCreate = async () => {
    if (!createName.trim() || !createAgentId) return
    setCreateLoading(true)
    try {
      const ch = await apiClient.createWAChannel({ name: createName.trim(), agent_id: createAgentId })
      setChannels((prev) => [ch, ...prev])
      setShowCreate(false)
      setCreateName("")
      setCreateAgentId("")
      toast.success("Channel created")
    } catch {
      toast.error("Failed to create channel")
    } finally {
      setCreateLoading(false)
    }
  }

  const handleDelete = async (ch: WAChannel) => {
    const ok = await confirmDelete()
    if (!ok) return
    try {
      await apiClient.deleteWAChannel(ch.id)
      setChannels((prev) => prev.filter((c) => c.id !== ch.id))
      toast.success("Channel deleted")
    } catch {
      toast.error("Failed to delete channel")
    }
  }

  const agentName = (id: string) => agents.find((a) => String(a.id) === String(id))?.name ?? id

  return (
    <div className="flex-1 overflow-auto p-6">
      <ConfirmDialog />

      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageCircle className="h-5 w-5 text-muted-foreground" />
            <h1 className="text-lg font-semibold">Channels</h1>
          </div>
          <Button size="sm" onClick={() => setShowCreate(true)} className="gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            New Channel
          </Button>
        </div>

        <p className="text-sm text-muted-foreground">
          Connect agents to WhatsApp accounts. Messages sent to the linked number are processed by the assigned agent.
        </p>

        {/* Channel list */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : channels.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground border rounded-lg border-dashed">
            <MessageCircle className="h-8 w-8 opacity-40" />
            <p className="text-sm">No channels yet. Create one to get started.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {channels.map((ch) => (
              <div
                key={ch.id}
                className="flex items-center gap-4 px-4 py-3 rounded-lg border bg-card hover:bg-accent/30 transition-colors"
              >
                {/* Status icon */}
                <div className="shrink-0">
                  {ch.status === "connected"
                    ? <Wifi className="h-4 w-4 text-emerald-500" />
                    : <WifiOff className="h-4 w-4 text-muted-foreground" />
                  }
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">{ch.name}</span>
                    <StatusBadge status={ch.status} />
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-2">
                    <span>Agent: {agentName(ch.agent_id)}</span>
                    {ch.wa_phone && <span>· {ch.wa_phone}</span>}
                    {ch.allowed_jids && ch.allowed_jids.length > 0 && (
                      <span>· {ch.allowed_jids.length} allowed contact{ch.allowed_jids.length !== 1 ? "s" : ""}</span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0">
                  {ch.status === "pending_qr" && (
                    <Link href={`/channels/${ch.id}`}>
                      <Button variant="outline" size="sm" className="gap-1.5 h-7 text-xs">
                        <QrCode className="h-3 w-3" />
                        Scan QR
                      </Button>
                    </Link>
                  )}
                  <Link href={`/channels/${ch.id}`}>
                    <Button variant="ghost" size="icon" className="h-7 w-7">
                      <Settings2 className="h-3.5 w-3.5" />
                    </Button>
                  </Link>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive hover:text-destructive"
                    onClick={() => handleDelete(ch)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create dialog */}
      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New WhatsApp Channel</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>Channel name</Label>
              <Input
                placeholder="e.g. Support Bot"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Agent</Label>
              <Select value={createAgentId} onValueChange={setCreateAgentId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select an agent" />
                </SelectTrigger>
                <SelectContent>
                  {agents.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button
              onClick={handleCreate}
              disabled={!createName.trim() || !createAgentId || createLoading}
            >
              {createLoading && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
