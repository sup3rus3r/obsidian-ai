"use client"

import { useEffect, useState } from "react"
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
import { Badge } from "@/components/ui/badge"
import { apiClient } from "@/lib/api-client"
import { toast } from "sonner"
import { Loader2, Copy, Trash2, Plus, Key, AlertTriangle } from "lucide-react"
import type { AgentApiKey, AgentApiKeyCreateResponse } from "@/types/playground"

interface AgentApiDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string | null
  agentName: string
}

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8001"

function copy(text: string, label: string) {
  navigator.clipboard.writeText(text)
  toast.success(`${label} copied`)
}

export function AgentApiDialog({ open, onOpenChange, agentId, agentName }: AgentApiDialogProps) {
  const [clients, setClients] = useState<AgentApiKey[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newKeyName, setNewKeyName] = useState("")
  const [justCreated, setJustCreated] = useState<AgentApiKeyCreateResponse | null>(null)
  const [publicUrl, setPublicUrl] = useState<string | null>(null)
  const [tunnelEnabled, setTunnelEnabled] = useState(false)

  useEffect(() => {
    if (!open || !agentId) return
    setJustCreated(null)
    setLoading(true)
    apiClient
      .listAgentApiClients(agentId)
      .then(setClients)
      .catch(() => setClients([]))
      .finally(() => setLoading(false))
    apiClient
      .getTunnelStatus()
      .then((s) => {
        setTunnelEnabled(s.enabled)
        setPublicUrl(s.public_url)
      })
      .catch(() => {
        setTunnelEnabled(false)
        setPublicUrl(null)
      })
  }, [open, agentId])

  const handleCreate = async () => {
    if (!agentId || !newKeyName.trim()) return
    setCreating(true)
    try {
      const created = await apiClient.createAgentApiClient(agentId, newKeyName.trim())
      setJustCreated(created)
      setClients((prev) => [{ ...created }, ...prev])
      setNewKeyName("")
    } catch (err: any) {
      toast.error(err?.message || "Failed to create API key")
    } finally {
      setCreating(false)
    }
  }

  const handleRevoke = async (clientId: string) => {
    if (!agentId) return
    try {
      await apiClient.revokeAgentApiClient(agentId, clientId)
      setClients((prev) => prev.map((c) => (c.client_id === clientId ? { ...c, is_active: false } : c)))
      toast.success("API key revoked")
    } catch (err: any) {
      toast.error(err?.message || "Failed to revoke key")
    }
  }

  const baseUrl = publicUrl || BACKEND_URL
  const exampleClientId = justCreated?.client_id || clients.find((c) => c.is_active)?.client_id || "<X-API-Key>"
  const curlExample = `curl -X POST ${baseUrl}/api/v1/agent/chat \\
  -H "X-API-Key: ${exampleClientId}" \\
  -H "X-API-Secret: <X-API-Secret>" \\
  -H "Content-Type: application/json" \\
  -d '{"message": "Hello!"}'`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showFullscreenButton className="sm:max-w-[60vw]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Key className="h-4 w-4" />
            API Access — {agentName}
          </DialogTitle>
          <DialogDescription>
            Generate a key to call this agent — with its tools, system prompt, and memory — from other apps and platforms.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {!tunnelEnabled && (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                No public tunnel is configured, so this is only reachable from this network (e.g. other apps on the
                same machine or LAN). To let apps outside your network call this agent, set{" "}
                <code className="font-mono">ENABLE_NGROK_TUNNEL=true</code> (and optionally{" "}
                <code className="font-mono">NGROK_AUTHTOKEN</code>) on the backend and restart it.
              </div>
            </div>
          )}
          {tunnelEnabled && publicUrl && (
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="secondary" className="gap-1">
                Public URL
              </Badge>
              <code className="font-mono text-muted-foreground">{publicUrl}</code>
            </div>
          )}

          <div className="grid gap-2">
            <Label>Generate a new key</Label>
            <div className="flex gap-2">
              <Input
                placeholder="e.g. Zapier integration"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
              <Button onClick={handleCreate} disabled={creating || !newKeyName.trim()}>
                {creating ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Plus className="h-4 w-4 mr-2" />}
                Generate
              </Button>
            </div>
          </div>

          {justCreated && (
            <div className="rounded-md border border-border p-3 space-y-2 bg-muted/30">
              <p className="text-xs font-medium text-foreground">{justCreated.message}</p>
              <div className="grid gap-1.5">
                <div className="flex items-center gap-2">
                  <Label className="text-xs w-16 shrink-0">Key ID</Label>
                  <code className="flex-1 text-xs font-mono truncate">{justCreated.client_id}</code>
                  <Button variant="ghost" size="icon-sm" onClick={() => copy(justCreated.client_id, "Key ID")}>
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <Label className="text-xs w-16 shrink-0">Secret</Label>
                  <code className="flex-1 text-xs font-mono truncate">{justCreated.client_secret}</code>
                  <Button variant="ghost" size="icon-sm" onClick={() => copy(justCreated.client_secret, "Secret")}>
                    <Copy className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </div>
          )}

          <div className="grid gap-2">
            <Label>Existing keys</Label>
            {loading ? (
              <div className="flex justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            ) : clients.length === 0 ? (
              <p className="text-xs text-muted-foreground py-2">No API keys yet for this agent.</p>
            ) : (
              <div className="rounded-md border border-border divide-y divide-border">
                {clients.map((c) => (
                  <div key={c.client_id} className="flex items-center justify-between px-3 py-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium truncate">{c.name}</span>
                        <Badge variant={c.is_active ? "secondary" : "outline"} className="text-[10px] px-1.5 py-0">
                          {c.is_active ? "active" : "revoked"}
                        </Badge>
                      </div>
                      <code className="text-[11px] text-muted-foreground font-mono truncate block">{c.client_id}</code>
                    </div>
                    {c.is_active && (
                      <Button variant="ghost" size="icon-sm" onClick={() => handleRevoke(c.client_id)} title="Revoke key">
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <Label>Example request</Label>
              <Button variant="ghost" size="sm" onClick={() => copy(curlExample, "Example request")}>
                <Copy className="h-3.5 w-3.5 mr-1.5" />
                Copy
              </Button>
            </div>
            <pre className="text-[11px] bg-muted/60 rounded-md p-3 overflow-x-auto font-mono whitespace-pre-wrap">
              {curlExample}
            </pre>
            <p className="text-[11px] text-muted-foreground">
              The response includes a <code className="font-mono">conversation_id</code> — pass it back on the next
              call to continue the same conversation with full memory.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
