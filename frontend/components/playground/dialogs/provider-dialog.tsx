"use client"

import { useState, useEffect } from "react"
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useSession } from "next-auth/react"
import { createProvider, testProvider, listSecrets } from "@/app/api/playground"
import { usePlaygroundStore } from "@/stores/playground-store"
import { Loader2, CheckCircle2, XCircle, KeyRound, Lock } from "lucide-react"
import type { Secret } from "@/types/playground"

const PROVIDER_TYPES = [
  { value: "ollama", label: "Ollama (Local)", defaultUrl: "http://localhost:11434", needsKey: false },
  { value: "openai", label: "OpenAI", defaultUrl: "", needsKey: true },
  { value: "anthropic", label: "Anthropic", defaultUrl: "", needsKey: true },
  { value: "google", label: "Google Gemini", defaultUrl: "", needsKey: true },
  { value: "openrouter", label: "OpenRouter", defaultUrl: "https://openrouter.ai/api/v1", needsKey: true },
  { value: "custom", label: "Custom (OpenAI-compatible)", defaultUrl: "", needsKey: false },
]

interface ProviderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ProviderDialog({ open, onOpenChange }: ProviderDialogProps) {
  const { data: session } = useSession()
  const setProviders = usePlaygroundStore((s) => s.setProviders)
  const providers = usePlaygroundStore((s) => s.providers)

  const [name, setName] = useState("")
  const [providerType, setProviderType] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [modelId, setModelId] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "connected" | "failed">("idle")

  // Secret selection state
  const [keySource, setKeySource] = useState<"manual" | "secret">("manual")
  const [secrets, setSecrets] = useState<Secret[]>([])
  const [selectedSecretId, setSelectedSecretId] = useState("")
  const [secretsLoading, setSecretsLoading] = useState(false)

  const selectedType = PROVIDER_TYPES.find((p) => p.value === providerType)

  // Fetch secrets when dialog opens and provider needs a key
  useEffect(() => {
    if (open && session?.accessToken) {
      setSecretsLoading(true)
      listSecrets(session.accessToken)
        .then(setSecrets)
        .catch(() => setSecrets([]))
        .finally(() => setSecretsLoading(false))
    }
  }, [open, session?.accessToken])

  const handleProviderTypeChange = (value: string) => {
    setProviderType(value)
    const type = PROVIDER_TYPES.find((p) => p.value === value)
    if (type?.defaultUrl) {
      setBaseUrl(type.defaultUrl)
    } else {
      setBaseUrl("")
    }
    setTestStatus("idle")
  }

  const handleCreate = async () => {
    if (!session?.accessToken || !name || !providerType || !modelId) return
    setLoading(true)
    setError("")
    try {
      const payload: Parameters<typeof createProvider>[1] = {
        name,
        provider_type: providerType,
        base_url: baseUrl || undefined,
        model_id: modelId,
      }

      if (selectedType?.needsKey) {
        if (keySource === "secret" && selectedSecretId) {
          payload.secret_id = selectedSecretId
        } else if (keySource === "manual" && apiKey) {
          payload.api_key = apiKey
        }
      }

      const newProvider = await createProvider(session.accessToken, payload)
      setProviders([...providers, newProvider])
      resetForm()
      onOpenChange(false)
    } catch (err: any) {
      console.error("Failed to create provider:", err)
      setError(err?.message || "Failed to create provider")
    } finally {
      setLoading(false)
    }
  }

  const resetForm = () => {
    setName("")
    setProviderType("")
    setBaseUrl("")
    setApiKey("")
    setModelId("")
    setKeySource("manual")
    setSelectedSecretId("")
    setTestStatus("idle")
    setError("")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Add LLM Provider</DialogTitle>
          <DialogDescription>
            Configure a connection to an LLM provider.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="provider-type">Provider Type</Label>
            <Select value={providerType} onValueChange={handleProviderTypeChange}>
              <SelectTrigger>
                <SelectValue placeholder="Select provider..." />
              </SelectTrigger>
              <SelectContent>
                {PROVIDER_TYPES.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="name">Display Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`My ${selectedType?.label || "Provider"}`}
            />
          </div>

          {(providerType === "ollama" || providerType === "custom" || providerType === "openrouter") && (
            <div className="grid gap-2">
              <Label htmlFor="base-url">Base URL</Label>
              <Input
                id="base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:11434"
              />
            </div>
          )}

          {selectedType?.needsKey && (
            <div className="grid gap-2">
              <Label>API Key</Label>

              {/* Toggle between manual entry and secret selection */}
              <div className="flex gap-1 rounded-md border p-1">
                <button
                  type="button"
                  onClick={() => { setKeySource("manual"); setSelectedSecretId("") }}
                  className={`flex-1 flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-sm transition-colors ${
                    keySource === "manual"
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <KeyRound className="h-3.5 w-3.5" />
                  Enter key
                </button>
                <button
                  type="button"
                  onClick={() => { setKeySource("secret"); setApiKey("") }}
                  className={`flex-1 flex items-center justify-center gap-1.5 rounded px-3 py-1.5 text-sm transition-colors ${
                    keySource === "secret"
                      ? "bg-primary text-primary-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Lock className="h-3.5 w-3.5" />
                  Use from secrets
                </button>
              </div>

              {keySource === "manual" ? (
                <Input
                  id="api-key"
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                />
              ) : (
                <Select value={selectedSecretId} onValueChange={setSelectedSecretId}>
                  <SelectTrigger>
                    <SelectValue
                      placeholder={
                        secretsLoading
                          ? "Loading secrets..."
                          : secrets.length === 0
                          ? "No secrets found -- add one in Settings"
                          : "Select a secret..."
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {secrets.map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name} ({s.masked_value})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          )}

          <div className="grid gap-2">
            <Label htmlFor="model-id">Model ID</Label>
            <Input
              id="model-id"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              placeholder={
                providerType === "ollama"
                  ? "llama3.2"
                  : providerType === "openai"
                  ? "gpt-4o"
                  : providerType === "anthropic"
                  ? "claude-sonnet-4-20250514"
                  : providerType === "google"
                  ? "gemini-2.0-flash"
                  : "model-name"
              }
            />
          </div>

          {/* Connection test status */}
          {testStatus !== "idle" && (
            <div className="flex items-center gap-2 text-sm">
              {testStatus === "testing" && (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Testing connection...</span>
                </>
              )}
              {testStatus === "connected" && (
                <>
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                  <span className="text-emerald-500">Connected</span>
                </>
              )}
              {testStatus === "failed" && (
                <>
                  <XCircle className="h-4 w-4 text-red-500" />
                  <span className="text-red-500">Connection failed</span>
                </>
              )}
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={loading || !name || !providerType || !modelId}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Create Provider
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
