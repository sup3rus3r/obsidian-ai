"use client"

import { useEffect, useRef, useState, useCallback } from "react"
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
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
  Upload,
  Trash2,
  CheckCircle2,
  StopCircle,
  Radio,
} from "lucide-react"
import { toast } from "sonner"

// ── Voice options ─────────────────────────────────────────────────────────────

const QWEN_VOICES = [
  { value: "Ryan",     label: "Ryan — Dynamic male (English)",        lang: "en" },
  { value: "Aiden",    label: "Aiden — Sunny American male (English)", lang: "en" },
  { value: "Vivian",   label: "Vivian — Bright young female (Chinese)", lang: "zh" },
  { value: "Serena",   label: "Serena — Warm gentle female (Chinese)", lang: "zh" },
  { value: "Uncle_Fu", label: "Uncle Fu — Low mellow male (Chinese)",  lang: "zh" },
  { value: "Dylan",    label: "Dylan — Natural male (Chinese)",         lang: "zh" },
  { value: "Eric",     label: "Eric — Husky male (Chinese)",            lang: "zh" },
  { value: "Ono_Anna", label: "Ono Anna — Playful female (Japanese)",   lang: "ja" },
  { value: "Sohee",   label: "Sohee — Warm female (Korean)",           lang: "ko" },
]

const CLASSIC_VOICES = [
  { value: "marius",  label: "Marius (Male)" },
  { value: "javert",  label: "Javert (Male)" },
  { value: "jean",    label: "Jean (Male)" },
  { value: "alba",    label: "Alba (Female)" },
  { value: "fantine", label: "Fantine (Female)" },
  { value: "cosette", label: "Cosette (Female)" },
  { value: "eponine", label: "Eponine (Female)" },
  { value: "azelma",  label: "Azelma (Female)" },
]

// Guided script to capture a good voice sample
const VOICE_GUIDE_SCRIPT = `Hi, my name is [your name] and I'm recording a short voice sample. The quick brown fox jumps over the lazy dog. I believe that every conversation is an opportunity to connect, learn, and grow. It's a beautiful day today, and I'm looking forward to what's ahead. Thank you for listening.`

// ── Helpers ────────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: WAChannel["status"] }) {
  if (status === "connected")   return <Badge className="bg-emerald-500/15 text-emerald-600 border-emerald-500/30">Connected</Badge>
  if (status === "pending_qr") return <Badge className="bg-amber-500/15 text-amber-600 border-amber-500/30">Awaiting QR scan</Badge>
  return <Badge variant="secondary">Disconnected</Badge>
}

// ── Voice Clone Dialog ─────────────────────────────────────────────────────────

interface VoiceCloneDialogProps {
  open: boolean
  onOpenChange: (v: boolean) => void
  channelId: string
  onSuccess: () => void
}

function VoiceCloneDialog({ open, onOpenChange, channelId, onSuccess }: VoiceCloneDialogProps) {
  const [mode, setMode] = useState<"guide" | "record" | "upload">("guide")
  const [recording, setRecording] = useState(false)
  const [recorded, setRecorded] = useState<Blob | null>(null)
  const [recordedUrl, setRecordedUrl] = useState<string | null>(null)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [refText, setRefText] = useState("")
  const [uploading, setUploading] = useState(false)
  const [recordSeconds, setRecordSeconds] = useState(0)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Reset when dialog opens
  useEffect(() => {
    if (open) {
      setMode("guide")
      setRecording(false)
      setRecorded(null)
      setRecordedUrl(null)
      setUploadFile(null)
      setRefText("")
      setRecordSeconds(0)
    }
  }, [open])

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunksRef.current = []
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" })
      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" })
        setRecorded(blob)
        setRecordedUrl(URL.createObjectURL(blob))
        stream.getTracks().forEach((t) => t.stop())
      }
      mr.start()
      mediaRecorderRef.current = mr
      setRecording(true)
      setRecordSeconds(0)
      timerRef.current = setInterval(() => setRecordSeconds((s) => s + 1), 1000)
    } catch {
      toast.error("Microphone access denied")
    }
  }

  const stopRecording = () => {
    mediaRecorderRef.current?.stop()
    setRecording(false)
    if (timerRef.current) clearInterval(timerRef.current)
  }

  const handleUpload = async () => {
    const blob = uploadFile ?? recorded
    if (!blob) return
    setUploading(true)
    try {
      await apiClient.uploadWAVoiceSample(channelId, blob, refText.trim())
      toast.success("Voice sample saved")
      onOpenChange(false)
      onSuccess()
    } catch (e: any) {
      toast.error(e.message || "Upload failed")
    } finally {
      setUploading(false)
    }
  }

  const hasAudio = !!recorded || !!uploadFile

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mic className="h-4 w-4 text-violet-500" />
            Record your voice
          </DialogTitle>
          <DialogDescription>
            A short clip of your voice is used to clone it. Read the script below for best results.
          </DialogDescription>
        </DialogHeader>

        {/* Step 1: guided script */}
        {mode === "guide" && (
          <div className="space-y-4">
            <div className="rounded-md border bg-muted/30 p-4">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Read this aloud:</p>
              <p className="text-sm leading-relaxed italic">"{VOICE_GUIDE_SCRIPT}"</p>
            </div>
            <p className="text-xs text-muted-foreground">
              Tip: speak naturally at a normal pace in a quiet environment. The recording should be at least 5 seconds.
            </p>
            <div className="flex gap-2">
              <Button
                className="flex-1 gap-2"
                onClick={() => setMode("record")}
              >
                <Mic className="h-4 w-4" />
                Record now
              </Button>
              <Button
                variant="outline"
                className="flex-1 gap-2"
                onClick={() => setMode("upload")}
              >
                <Upload className="h-4 w-4" />
                Upload file
              </Button>
            </div>
          </div>
        )}

        {/* Step 2a: record */}
        {mode === "record" && (
          <div className="space-y-4">
            {/* Script reminder */}
            <div className="rounded-md border bg-muted/20 p-3 max-h-28 overflow-y-auto">
              <p className="text-xs text-muted-foreground italic leading-relaxed">"{VOICE_GUIDE_SCRIPT}"</p>
            </div>

            <div className="flex flex-col items-center gap-3 py-2">
              {!recorded && (
                <Button
                  size="lg"
                  variant={recording ? "destructive" : "default"}
                  className="gap-2 w-40"
                  onClick={recording ? stopRecording : startRecording}
                >
                  {recording ? (
                    <><StopCircle className="h-4 w-4" /> Stop ({recordSeconds}s)</>
                  ) : (
                    <><Radio className="h-4 w-4" /> Start recording</>
                  )}
                </Button>
              )}
              {recording && (
                <p className="text-xs text-muted-foreground animate-pulse">Recording… read the script above</p>
              )}
              {recorded && recordedUrl && (
                <div className="w-full space-y-2">
                  <p className="text-xs text-emerald-600 flex items-center gap-1.5">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Recording captured ({recordSeconds}s)
                  </p>
                  <audio src={recordedUrl} controls className="w-full h-8" />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs text-muted-foreground gap-1"
                    onClick={() => { setRecorded(null); setRecordedUrl(null); setRecordSeconds(0) }}
                  >
                    <Trash2 className="h-3 w-3" /> Re-record
                  </Button>
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Transcript <span className="text-muted-foreground">(optional — improves quality)</span></Label>
              <Textarea
                value={refText}
                onChange={(e) => setRefText(e.target.value)}
                placeholder="Paste exactly what you said in the recording…"
                rows={3}
                className="text-xs"
              />
              <button
                type="button"
                className="text-xs text-violet-600 hover:underline"
                onClick={() => setRefText(VOICE_GUIDE_SCRIPT.replace(/\[your name\]/g, ""))}
              >
                Use the guide script as transcript
              </button>
            </div>
          </div>
        )}

        {/* Step 2b: upload */}
        {mode === "upload" && (
          <div className="space-y-4">
            <div
              className="border-2 border-dashed rounded-md p-6 text-center cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="h-6 w-6 mx-auto mb-2 text-muted-foreground" />
              {uploadFile ? (
                <p className="text-sm font-medium">{uploadFile.name}</p>
              ) : (
                <p className="text-sm text-muted-foreground">Click to select an audio file (WAV, MP3, OGG, WebM, MP4)</p>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              />
            </div>

            <div className="space-y-1.5">
              <Label className="text-xs">Transcript <span className="text-muted-foreground">(optional — improves quality)</span></Label>
              <Textarea
                value={refText}
                onChange={(e) => setRefText(e.target.value)}
                placeholder="What is said in the audio file…"
                rows={3}
                className="text-xs"
              />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          {mode !== "guide" && (
            <Button
              onClick={handleUpload}
              disabled={!hasAudio || uploading}
              className="gap-1.5"
            >
              {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Save voice sample
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function ChannelDetailPage() {
  const { data: authSession } = useSession()
  const params = useParams()
  const router = useRouter()
  const channelId = params.id as string

  const [channel, setChannel] = useState<WAChannel | null>(null)
  const [agents, setAgents] = useState<Agent[]>([])
  const [isLoading, setIsLoading] = useState(true)

  // General settings
  const [editName, setEditName] = useState("")
  const [editAgentId, setEditAgentId] = useState("")
  const [editAllowedJids, setEditAllowedJids] = useState<string[]>([])
  const [editRejectMessage, setEditRejectMessage] = useState("")
  const [allowAll, setAllowAll] = useState(true)
  const [newJid, setNewJid] = useState("")
  const [isGroupEntry, setIsGroupEntry] = useState(false)
  const [saving, setSaving] = useState(false)

  // Voice reply settings
  const [voiceReplyEnabled, setVoiceReplyEnabled] = useState(false)
  const [voiceReplyJids, setVoiceReplyJids] = useState<string[]>([])
  const [voiceReplyAllContacts, setVoiceReplyAllContacts] = useState(true)
  const [voiceReplyVoice, setVoiceReplyVoice] = useState("Ryan")
  const [ttsBackend, setTtsBackend] = useState<"auto" | "qwen" | "classic">("auto")
  const [newVoiceJid, setNewVoiceJid] = useState("")

  // Voice clone dialog
  const [cloneDialogOpen, setCloneDialogOpen] = useState(false)
  const [deletingClone, setDeletingClone] = useState(false)

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
      applyChannel(ch)
      setAgents(ags)
      if (ch.status === "pending_qr") startQRStream()
    } catch {
      toast.error("Failed to load channel")
    } finally {
      setIsLoading(false)
    }
  }

  const applyChannel = (ch: WAChannel) => {
    setChannel(ch)
    setEditName(ch.name)
    setEditAgentId(String(ch.agent_id))
    const jids = ch.allowed_jids ?? []
    setAllowAll(jids.length === 0)
    setEditAllowedJids(jids)
    setEditRejectMessage(ch.reject_message ?? "")
    setVoiceReplyEnabled(ch.voice_reply_enabled ?? false)
    setVoiceReplyJids(ch.voice_reply_jids ?? [])
    setVoiceReplyAllContacts((ch.voice_reply_jids ?? []).length === 0)
    setVoiceReplyVoice(ch.voice_reply_voice ?? "Ryan")
    setTtsBackend((ch.tts_backend as any) ?? "auto")
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
      } catch { /* ignore */ }
    }
    es.onerror = () => { setQrConnecting(false); es.close() }
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
        tts_backend: ttsBackend,
      }
      const updated = await apiClient.updateWAChannel(channelId, updates)
      applyChannel(updated)
      toast.success("Saved")
    } catch {
      toast.error("Failed to save")
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteClone = async () => {
    if (!confirm("Remove your voice sample? Voice cloning will be disabled.")) return
    setDeletingClone(true)
    try {
      await apiClient.deleteWAVoiceSample(channelId)
      toast.success("Voice sample removed")
      setChannel((prev) => prev ? { ...prev, has_voice_clone: false, voice_clone_audio_path: null, voice_clone_ref_text: null } : prev)
    } catch {
      toast.error("Failed to remove voice sample")
    } finally {
      setDeletingClone(false)
    }
  }

  const addJid = () => {
    const jid = newJid.trim()
    if (!jid) return
    const normalised = isGroupEntry
      ? jid
      : jid.includes("@") ? jid : `${jid.replace(/\D/g, "")}@s.whatsapp.net`
    if (!editAllowedJids.includes(normalised)) setEditAllowedJids((prev) => [...prev, normalised])
    setNewJid("")
    setIsGroupEntry(false)
  }

  const removeJid = (jid: string) => setEditAllowedJids((prev) => prev.filter((j) => j !== jid))

  const addVoiceJid = () => {
    const jid = newVoiceJid.trim()
    if (!jid) return
    const normalised = jid.includes("@") ? jid : `${jid.replace(/\D/g, "")}@s.whatsapp.net`
    if (!voiceReplyJids.includes(normalised)) setVoiceReplyJids((prev) => [...prev, normalised])
    setNewVoiceJid("")
  }

  const removeVoiceJid = (jid: string) => setVoiceReplyJids((prev) => prev.filter((j) => j !== jid))

  const voiceOptions = ttsBackend === "classic" ? CLASSIC_VOICES : QWEN_VOICES

  if (isLoading) return (
    <div className="flex items-center justify-center h-full">
      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
  )

  if (!channel) return (
    <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
      Channel not found.
    </div>
  )

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-2xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => router.push("/channels")}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex-1 flex items-center gap-2">
            <h1 className="text-lg font-semibold">{channel.name}</h1>
            <StatusBadge status={channel.status} />
          </div>
        </div>

        {/* Connection */}
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
                    <RefreshCw className="h-3 w-3" /> Refresh QR
                  </Button>
                </>
              )}
            </div>
          )}
        </div>

        <Separator />

        {/* Settings */}
        <div className="space-y-5">
          <p className="text-sm font-medium">Channel Settings</p>

          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
          </div>

          <div className="space-y-1.5">
            <Label>Agent</Label>
            <Select value={editAgentId} onValueChange={setEditAgentId}>
              <SelectTrigger><SelectValue placeholder="Select agent" /></SelectTrigger>
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
                <p className="text-xs text-muted-foreground mt-0.5">Restrict which contacts this channel responds to.</p>
              </div>
              <Button variant={allowAll ? "default" : "outline"} size="sm" className="text-xs h-7" onClick={() => setAllowAll(!allowAll)}>
                {allowAll ? "Allow all" : "Whitelist only"}
              </Button>
            </div>
            {!allowAll && (
              <div className="space-y-2">
                {editAllowedJids.map((jid) => (
                  <div key={jid} className="flex items-center gap-2 text-sm">
                    {!jid.includes("@") && <Badge variant="secondary" className="text-xs px-1.5 py-0 shrink-0">group</Badge>}
                    <span className="flex-1 truncate font-mono text-xs bg-muted px-2 py-1 rounded">{jid}</span>
                    <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeJid(jid)}><X className="h-3 w-3" /></Button>
                  </div>
                ))}
                <div className="flex gap-2">
                  <Button size="sm" variant={isGroupEntry ? "default" : "outline"} className="h-8 text-xs shrink-0" onClick={() => setIsGroupEntry((v) => !v)}>Group</Button>
                  <Input placeholder={isGroupEntry ? "Group name" : "Phone number (e.g. 15551234567)"} className="text-xs h-8" value={newJid} onChange={(e) => setNewJid(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addJid()} />
                  <Button size="sm" variant="outline" className="h-8 px-2" onClick={addJid}><Plus className="h-3.5 w-3.5" /></Button>
                </div>
              </div>
            )}
            <div className="space-y-1.5">
              <Label className="text-xs">Reply to blocked senders <span className="text-muted-foreground">(optional)</span></Label>
              <Input placeholder="e.g. Sorry, I can only respond to approved contacts." className="text-xs" value={editRejectMessage} onChange={(e) => setEditRejectMessage(e.target.value)} />
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
                  <p className="text-xs text-muted-foreground mt-0.5">Reply with a generated voice note.</p>
                </div>
              </div>
              <Button variant={voiceReplyEnabled ? "default" : "outline"} size="sm" className="text-xs h-7" onClick={() => setVoiceReplyEnabled((v) => !v)}>
                {voiceReplyEnabled ? "Enabled" : "Disabled"}
              </Button>
            </div>

            {voiceReplyEnabled && (
              <div className="space-y-4 pl-6">
                {/* TTS backend */}
                <div className="space-y-1.5">
                  <Label className="text-xs">TTS engine</Label>
                  <Select value={ttsBackend} onValueChange={(v) => setTtsBackend(v as any)}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto" className="text-xs">Auto — GPU if available, CPU otherwise</SelectItem>
                      <SelectItem value="qwen" className="text-xs">Qwen3-TTS — high quality (requires GPU)</SelectItem>
                      <SelectItem value="classic" className="text-xs">Classic — CPU friendly (Pocket / Kokoro)</SelectItem>
                    </SelectContent>
                  </Select>
                  {ttsBackend === "qwen" && (
                    <p className="text-xs text-amber-600">Requires a CUDA-capable GPU with ~4–10GB VRAM.</p>
                  )}
                </div>

                {/* Voice picker */}
                <div className="space-y-1.5">
                  <Label className="text-xs">Preset voice</Label>
                  <Select value={voiceReplyVoice} onValueChange={setVoiceReplyVoice}>
                    <SelectTrigger className="h-8 w-full text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {voiceOptions.map((v) => (
                        <SelectItem key={v.value} value={v.value} className="text-xs">{v.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {ttsBackend !== "classic" && (
                    <p className="text-xs text-muted-foreground">This preset is used when no voice clone sample is set.</p>
                  )}
                </div>

                {/* Voice clone (Qwen only) */}
                {ttsBackend !== "classic" && (
                  <div className="space-y-2 rounded-md border p-3 bg-muted/20">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs font-medium flex items-center gap-1.5">
                          <Mic className="h-3.5 w-3.5 text-violet-500" />
                          Your voice clone
                        </p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Replies will sound like you.
                        </p>
                      </div>
                      {channel.has_voice_clone ? (
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs text-emerald-600 flex items-center gap-1">
                            <CheckCircle2 className="h-3.5 w-3.5" /> Sample saved
                          </span>
                          <Button variant="ghost" size="icon" className="h-6 w-6 text-muted-foreground hover:text-destructive" onClick={handleDeleteClone} disabled={deletingClone}>
                            {deletingClone ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                          </Button>
                        </div>
                      ) : (
                        <Button size="sm" variant="outline" className="text-xs h-7 gap-1.5" onClick={() => setCloneDialogOpen(true)}>
                          <Mic className="h-3 w-3" />
                          Record / upload
                        </Button>
                      )}
                    </div>
                    {channel.has_voice_clone && (
                      <Button size="sm" variant="ghost" className="text-xs h-6 text-muted-foreground gap-1" onClick={() => setCloneDialogOpen(true)}>
                        <RefreshCw className="h-3 w-3" /> Replace sample
                      </Button>
                    )}
                  </div>
                )}

                {/* Per-contact voice targeting */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">Send voice replies to:</p>
                    <Button variant={voiceReplyAllContacts ? "default" : "outline"} size="sm" className="text-xs h-6" onClick={() => setVoiceReplyAllContacts((v) => !v)}>
                      {voiceReplyAllContacts ? "All contacts" : "Specific contacts"}
                    </Button>
                  </div>
                  {!voiceReplyAllContacts && (
                    <div className="space-y-1.5">
                      {voiceReplyJids.map((jid) => (
                        <div key={jid} className="flex items-center gap-2">
                          <span className="flex-1 truncate font-mono text-xs bg-muted px-2 py-1 rounded">{jid}</span>
                          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => removeVoiceJid(jid)}><X className="h-3 w-3" /></Button>
                        </div>
                      ))}
                      <div className="flex gap-2">
                        <Input placeholder="Phone number (e.g. 15551234567)" className="text-xs h-8" value={newVoiceJid} onChange={(e) => setNewVoiceJid(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addVoiceJid()} />
                        <Button size="sm" variant="outline" className="h-8 px-2" onClick={addVoiceJid}><Plus className="h-3.5 w-3.5" /></Button>
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

      {/* Voice clone dialog */}
      <VoiceCloneDialog
        open={cloneDialogOpen}
        onOpenChange={setCloneDialogOpen}
        channelId={channelId}
        onSuccess={load}
      />
    </div>
  )
}
