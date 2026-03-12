"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import { useParams, useRouter } from "next/navigation"
import { apiClient } from "@/lib/api-client"
import type { WAChannel, Agent, UpdateWAChannelRequest } from "@/types/playground"
import { AppRoutes } from "@/app/api/routes"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  ArrowLeft,
  Loader2,
  Wifi,
  WifiOff,
  RefreshCw,
  Plus,
  X,
  Save,
  Mic,
} from "lucide-react"
import { toast } from "sonner"

const VOICE_OPTIONS = [
  { value: "marius", label: "Marius (Male)" },
  { value: "javert", label: "Javert (Male)" },
  { value: "jean", label: "Jean (Male)" },
  { value: "alba", label: "Alba (Female)" },
  { value: "fantine", label: "Fantine (Female)" },
  { value: "cosette", label: "Cosette (Female)" },
  { value: "eponine", label: "Eponine (Female)" },
  { value: "azelma", label: "Azelma (Female)" },
]

function StatusBadge({ status }: { status: WAChannel["status"] }) {
  if (status === "connected") return <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30">Connected</Badge>
  if (status === "pending_qr") return <Badge className="bg-amber-500/15 text-amber-600 border-amber-500/30">Awaiting QR scan</Badge>
  return <Badge variant="secondary">Disconnected</Badge>
}

export default function ChannelDetailPage() {
  const { data: authSession } = useSession()
  const params = useParams()
  const router = useRouter()
  const channelId = params.id as string

  const [channel, setChannel] = useState<WAChannel | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [isLoading, setIsLoading] = useState(true)

  // Edit state
  const [editName, setEditName] = useState("")
  const [editAgentId, setEditAgentId] = useState("")
  const [editAllowedJids, setEditAllowedJids] = useState<string[]>([])
  const [editRejectMessage, setEditRejectMessage] = useState("")
  const [allowAll, setAllowAll] = useState(true)
  const [newJid, setNewJid] = useState("")
  const [isGroupEntry, setIsGroupEntry] = useState(false)
  const [saving, setSaving] = useState(false)

  // Voice reply state
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(false)
  const [voiceReplyJids, setVoiceReplyJids] = useState<string[]>([])
  const [voiceReplyAllContacts, setVoiceReplyAllContacts] = useState(true)
  const [voiceReplyVoice, setVoiceReplyVoice] = useState("marius")
  const [newVoiceJid, setNewVoiceJid] = useState("")

  // QR state
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null)
  const [qrConnecting, setQrConnecting] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)
  const qrEventSourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!authSession?.accessToken) return
    apiClient.setAccessToken(authSession.accessToken as string)
    load()
    return () => qrEventSourceRef.current?.close()
  }, [authSession?.accessToken, channelId])

  const load = async () => {
    setIsLoading(true)
    try {
      const [ch, ags] = await Promise.all([
        apiClient.getWAChannel(channelId),
        apiClient.listAgents(),
      ])
      setChannel(ch)
      setAgents(ags)
      setEditName(ch.name)
      setEditAgentId(String(ch.agent_id))
      const jids = ch.allowed_jids ?? []
      setAllowAll(jids.length === 0)
      setEditAllowedJids(jids)
      setEditRejectMessage(ch.reject_message ?? "")
      setVoiceReplyEnabled(ch.voice_reply_enabled ?? false)
      setVoiceReplyJids(ch.voice_reply_jids ?? [])
      setVoiceReplyAllContacts((ch.voice_reply_jids ?? []).length === 0)
      setVoiceReplyVoice(ch.voice_reply_voice ?? "marius")

      if (ch.status === "pending_qr") {
        startQRStream()
      }
    } catch {
      toast.error("Failed to load channel")
    } finally {
      setIsLoading(false)
    }
  }

  const startQRStream = () => {
    qrEventSourceRef.current?.close()
    setQrConnecting(true)
    setQrDataUrl(null)

    const es = new EventSource(`/api/wa/channels/${channelId}/qr`)
    qrEventSourceRef.current = es

    es.onmessage = async (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === "qr") {
          setQrDataUrl(data.qr)
          setQrConnecting(false)
        } else if (data.type === "connected") {
          es.close()
          setQrDataUrl(null)
          setQrConnecting(false)
          setChannel((prev) => prev ? { ...prev, status: "connected" } : prev)
          toast.success("WhatsApp connected!")
        } else if (data.error) {
          toast.error(`QR error: ${data.error}`)
          setQrConnecting(false)
          es.close()
        }
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      setQrConnecting(false)
      es.close()
    }
  }

  const handleConnect = async () => {
    setConnecting(true)
    try {
      await apiClient.connectWAChannel(channelId)
      setChannel((prev) => prev ? { ...prev, status: "pending_qr" } : prev)
      startQRStream()
    } catch {
      toast.error("Failed to connect channel")
    } finally {
      setConnecting(false)
    }
  }

  const handleDisconnect = async () => {
    setDisconnecting(true)
    try {
      qrEventSourceRef.current?.close()
      await apiClient.disconnectWAChannel(channelId)
      setChannel((prev) => prev ? { ...prev, status: "disconnected" } : prev)
      setQrDataUrl(null)
      toast.success("Disconnected")
    } catch {
      toast.error("Failed to disconnect")
    } finally {
      setDisconnecting(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const updates: UpdateWAChannelRequest = {
        name: editName.trim(),
        agent_id: editAgentId,
        allowed_jids: allowAll ? [] : editAllowedJids,
        reject_message: editRejectMessage.trim() || null,
        voice_reply_enabled: voiceReplyEnabled,
        voice_reply_jids: voiceReplyAllContacts ? [] : voiceReplyJids,
        voice_reply_voice: voiceReplyVoice,
      }
      const updated = await apiClient.updateWAChannel(channelId, updates)
      setChannel(updated)
      toast.success("Saved")
    } catch {
      toast.error("Failed to save")
    } finally {
      setSaving(false)
    }
  }

  const addJid = () => {
    const jid = newJid.trim()
    if (!jid) return
    const normalised = isGroupEntry
      ? jid
      : jid.includes("@") ? jid : `${jid.replace(/\D/g, "")}@s.whatsapp.net`
    if (!editAllowedJids.includes(normalised)) {
      setEditAllowedJids((prev) => [...prev, normalised])
    }
    setNewJid("")
    setIsGroupEntry(false)
  }

  const removeJid = (jid: string) => setEditAllowedJids((prev) => prev.filter((j) => j !== jid))

  const addVoiceJid = () => {
    const jid = newVoiceJid.trim()
    if (!jid) return
    const normalised = jid.includes("@") ? jid : `${jid.replace(/\D/g, "")}@s.whatsapp.net`
    if (!voiceReplyJids.includes(normalised)) {
      setVoiceReplyJids((prev) => [...prev, normalised])
    }
    setNewVoiceJid("")
  }

  const removeVoiceJid = (jid: string) => setVoiceReplyJids((prev) => prev.filter((j) => j !== jid))

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!channel) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        Channel not found.
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-2xl mx-auto space-y-6">
        {/* Back + header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => router.push("/channels")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex-1 flex items-center gap-2">
            <h1 className="text-lg font-semibold">{channel.name}</h1>
            <StatusBadge status={channel.status} />
          </div>
        </div>

        {/* Connection controls */}
        <div className="rounded-lg border p-4 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium">Connection</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                {channel.wa_phone ? `Linked to ${channel.wa_phone}` : "Not linked to a phone number yet"}
              </p>
            </div>
            <div className="flex gap-2">
              {channel.status !== "connected" ? (
                <Button size="sm" onClick={handleConnect} disabled={connecting || channel.status === "pending_qr"} className="gap-1.5">
                  {connecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
                  {channel.status === "pending_qr" ? "Waiting for scan..." : "Connect"}
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={handleDisconnect} disabled={disconnecting} className="gap-1.5">
                  {disconnecting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <WifiOff className="h-3.5 w-3.5" />}
                  Disconnect
                </Button>
              )}
            </div>
          </div>

          {/* QR Code */}
          {channel.status === "pending_qr" && (
            <div className="flex flex-col items-center gap-3 pt-2">
              {qrConnecting && !qrDataUrl && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Waiting for QR code...
                </div>
              )}
              {qrDataUrl && (
                <>
                  <p className="text-xs text-muted-foreground">Open WhatsApp → Linked Devices → Link a device</p>
                  <div className="rounded-xl border bg-white p-3 shadow-sm">
                    <img src={qrDataUrl} alt="WhatsApp QR code" width={280} height={280} className="block" />
                  </div>
                  <Button variant="ghost" size="sm" className="gap-1.5 text-xs" onClick={startQRStream}>
                    <RefreshCw className="h-3 w-3" />
                    Refresh QR
                  </Button>
                </>
              )}
            </div>
          )}
        </div>

        <Separator />

        {/* Settings form */}
        <div className="space-y-5">
          <p className="text-sm font-medium">Channel Settings</p>

          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
          </div>

          <div className="space-y-1.5">
            <Label>Agent</Label>
            <Select value={editAgentId} onValueChange={setEditAgentId}>
              <SelectTrigger>
                <SelectValue placeholder="Select agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>{a.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Separator />

          {/* Whitelist */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">Contact whitelist</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Restrict which WhatsApp contacts this channel responds to.
                </p>
              </div>
              <Button
                variant={allowAll ? "default" : "outline"}
                size="sm"
                className="text-xs h-7"
                onClick={() => setAllowAll(!allowAll)}
              >
                {allowAll ? "Allow all" : "Whitelist only"}
              </Button>
            </div>

            {!allowAll && (
              <div className="space-y-2">
                {editAllowedJids.map((jid) => (
                  <div key={jid} className="flex items-center gap-2 text-sm">
                    {!jid.includes("@") && (
                      <Badge variant="secondary" className="text-xs px-1.5 py-0 shrink-0">group</Badge>
                    )}
                    <span className="flex-1 truncate font-mono text-xs bg-muted px-2 py-1 rounded">{jid}</span>
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeJid(jid)}>
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant={isGroupEntry ? "default" : "outline"}
                    className="h-8 text-xs shrink-0"
                    onClick={() => setIsGroupEntry((v) => !v)}
                    title="Toggle to add a group name instead of a phone number"
                  >
                    Group
                  </Button>
                  <Input
                    placeholder={isGroupEntry ? "Group name (e.g. Sales Team)" : "Phone number (e.g. 15551234567)"}
                    className="text-xs h-8"
                    value={newJid}
                    onChange={(e) => setNewJid(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && addJid()}
                  />
                  <Button size="sm" variant="outline" className="h-8 px-2" onClick={addJid}>
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <Label className="text-xs">Reply to blocked senders <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                placeholder="e.g. Sorry, I can only respond to approved contacts."
                className="text-xs"
                value={editRejectMessage}
                onChange={(e) => setEditRejectMessage(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Leave empty to silently ignore blocked messages.</p>
            </div>
          </div>

          <Separator />

          {/* Voice replies */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Mic className="h-4 w-4 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium">Voice replies</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Reply to voice notes with a generated voice note.
                  </p>
                </div>
              </div>
              <Button
                variant={voiceReplyEnabled ? "default" : "outline"}
                size="sm"
                className="text-xs h-7"
                onClick={() => setVoiceReplyEnabled((v) => !v)}
              >
                {voiceReplyEnabled ? "Enabled" : "Disabled"}
              </Button>
            </div>

            {voiceReplyEnabled && (
              <div className="space-y-3 pl-6">
                <div className="space-y-1.5">
                  <Label className="text-xs">Voice</Label>
                  <Select value={voiceReplyVoice} onValueChange={setVoiceReplyVoice}>
                    <SelectTrigger className="h-8 w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {VOICE_OPTIONS.map((v) => (
                        <SelectItem key={v.value} value={v.value} className="text-xs">{v.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">Respond with voice to:</p>
                    <Button
                      variant={voiceReplyAllContacts ? "default" : "outline"}
                      size="sm"
                      className="text-xs h-6"
                      onClick={() => setVoiceReplyAllContacts((v) => !v)}
                    >
                      {voiceReplyAllContacts ? "All contacts" : "Specific contacts"}
                    </Button>
                  </div>

                  {!voiceReplyAllContacts && (
                    <div className="space-y-1.5">
                      {voiceReplyJids.map((jid) => (
                        <div key={jid} className="flex items-center gap-2">
                          <span className="flex-1 truncate font-mono text-xs bg-muted px-2 py-1 rounded">{jid}</span>
                          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeVoiceJid(jid)}>
                            <X className="h-3 w-3" />
                          </Button>
                        </div>
                      ))}
                      <div className="flex gap-2">
                        <Input
                          placeholder="Phone number (e.g. 15551234567)"
                          className="text-xs h-8"
                          value={newVoiceJid}
                          onChange={(e) => setNewVoiceJid(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && addVoiceJid()}
                        />
                        <Button size="sm" variant="outline" className="h-8 px-2" onClick={addVoiceJid}>
                          <Plus className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end">
          <Button onClick={handleSave} disabled={saving} className="gap-1.5">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            Save changes
          </Button>
        </div>
      </div>
    </div>
  )
}
