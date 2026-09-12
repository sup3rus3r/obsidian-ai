"use client"

import { useState, useEffect, useMemo } from "react"
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
import { createProvider, listSecrets, listFreeProviderCatalog } from "@/app/api/playground"
import { usePlaygroundStore } from "@/stores/playground-store"
import { apiClient } from "@/lib/api-client"
import { Loader2, CheckCircle2, XCircle, KeyRound, Lock, Info, ExternalLink } from "lucide-react"
import type { LLMProvider, Secret, FreeProviderCatalogEntry } from "@/types/playground"

interface ProviderTypeOption {
  value: string
  label: string
  defaultUrl: string
  needsKey: boolean
  /** Catalog entry — present only for free-tier providers. */
  free?: FreeProviderCatalogEntry
}

const BUILT_IN_PROVIDER_TYPES: ProviderTypeOption[] = [
  { value: "ollama", label: "Ollama (Local)", defaultUrl: "http://localhost:11434", needsKey: false },
  { value: "openai", label: "OpenAI", defaultUrl: "", needsKey: true },
  { value: "anthropic", label: "Anthropic", defaultUrl: "", needsKey: true },
  { value: "google", label: "Google Gemini", defaultUrl: "", needsKey: true },
  { value: "custom", label: "Custom (OpenAI-compatible)", defaultUrl: "", needsKey: false },
]

function freeEntryToOption(entry: FreeProviderCatalogEntry): ProviderTypeOption {
  return {
    value: entry.id,
    label: entry.label,
    defaultUrl: entry.base_url,
    // key_optional providers still accept a key to raise their rate limits,
    // so keep the key field available even though it isn't required.
    needsKey: entry.needs_key || entry.key_optional,
    free: entry,
  }
}

interface ProviderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** If provided, the dialog opens in edit mode for this provider */
  provider?: LLMProvider | null
  onUpdated?: (provider: LLMProvider) => void
}

export function ProviderDialog({ open, onOpenChange, provider, onUpdated }: ProviderDialogProps) {
  const { data: session } = useSession()
  const setProviders = usePlaygroundStore((s) => s.setProviders)
  const providers = usePlaygroundStore((s) => s.providers)

  const isEditMode = !!provider

  const [name, setName] = useState("")
  const [providerType, setProviderType] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [testStatus, setTestStatus] = useState<"idle" | "testing" | "connected" | "failed">("idle")

  // Secret selection state
  const [keySource, setKeySource] = useState<"manual" | "secret">("manual")
  const [secrets, setSecrets] = useState<Secret[]>([])
  const [selectedSecretId, setSelectedSecretId] = useState("")
  const [secretsLoading, setSecretsLoading] = useState(false)

  // Free-tier provider catalog, served from the backend so it can grow
  // without a frontend release.
  const [freeCatalog, setFreeCatalog] = useState<FreeProviderCatalogEntry[]>([])

  const freeOptions = useMemo(() => freeCatalog.map(freeEntryToOption), [freeCatalog])
  const providerTypes = useMemo(
    () => [...BUILT_IN_PROVIDER_TYPES, ...freeOptions],
    [freeOptions],
  )

  const selectedType = providerTypes.find((p) => p.value === providerType)
  const freeInfo = selectedType?.free
  // Cloudflare and friends ship a base URL with {account_id} still in it.
  const hasUnfilledTemplate = baseUrl.includes("{") && baseUrl.includes("}")

  // Pre-fill fields when editing an existing provider
  useEffect(() => {
    if (open && provider) {
      setName(provider.name)
      setProviderType(provider.provider_type)
      setBaseUrl(provider.base_url ?? "")
      setApiKey("")
      setTestStatus("idle")
      setError("")
      if (provider.secret_id) {
        setKeySource("secret")
        setSelectedSecretId(provider.secret_id)
      } else {
        setKeySource("manual")
        setSelectedSecretId("")
      }
    } else if (!open) {
      // Reset when closing (handles both create and edit)
      resetForm()
    }
  }, [open, provider])

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

  // Load the free-tier catalog once per open. A failure here is not fatal —
  // the built-in provider types still work, the free ones just don't appear.
  useEffect(() => {
    if (open && session?.accessToken) {
      listFreeProviderCatalog(session.accessToken)
        .then(setFreeCatalog)
        .catch(() => setFreeCatalog([]))
    }
  }, [open, session?.accessToken])

  const handleProviderTypeChange = (value: string) => {
    setProviderType(value)
    const type = [...BUILT_IN_PROVIDER_TYPES, ...freeCatalog.map(freeEntryToOption)]
      .find((p) => p.value === value)
    setBaseUrl(type?.defaultUrl || "")
    setTestStatus("idle")
  }

  const handleSubmit = async () => {
    if (!session?.accessToken || !name || !providerType) return
    setLoading(true)
    setError("")
    try {
      if (isEditMode && provider) {
        // Edit mode: build partial update payload
        const payload: Parameters<typeof apiClient.updateProvider>[1] = {
          name,
          provider_type: providerType,
          base_url: baseUrl || undefined,
        }

        if (selectedType?.needsKey) {
          if (keySource === "secret" && selectedSecretId) {
            payload.secret_id = selectedSecretId
            payload.api_key = undefined
          } else if (keySource === "manual" && apiKey) {
            payload.api_key = apiKey
            payload.secret_id = undefined
          }
        }

        const updated = await apiClient.updateProvider(provider.id, payload)
        onUpdated?.(updated)
        onOpenChange(false)
      } else {
        // Create mode
        const payload: Parameters<typeof createProvider>[1] = {
          name,
          provider_type: providerType,
          base_url: baseUrl || undefined,
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
      }
    } catch (err: any) {
      console.error("Failed to save provider:", err)
      setError(err?.message || "Failed to save provider")
    } finally {
      setLoading(false)
    }
  }

  const resetForm = () => {
    setName("")
    setProviderType("")
    setBaseUrl("")
    setApiKey("")
    setKeySource("manual")
    setSelectedSecretId("")
    setTestStatus("idle")
    setError("")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showFullscreenButton className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{isEditMode ? "Edit Provider" : "Add LLM Provider"}</DialogTitle>
          <DialogDescription>
            {isEditMode
              ? "Update provider settings or assign an API key / vault secret."
              : "Configure a connection to an LLM provider."}
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
                {BUILT_IN_PROVIDER_TYPES.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
                {freeOptions.length > 0 && (
                  <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                    Free tier
                  </div>
                )}
                {freeOptions.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    <span className="flex items-center gap-2">
                      {p.label}
                      {!p.free?.needs_key && (
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                          No key
                        </span>
                      )}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {freeInfo && (
            <div className="rounded-md border border-muted bg-muted/40 p-3 text-xs">
              <div className="flex gap-2">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <div className="space-y-1.5">
                  {freeInfo.caveat && <p className="text-muted-foreground">{freeInfo.caveat}</p>}
                  <p>
                    <span className="text-muted-foreground">Suggested model: </span>
                    <code className="rounded bg-background px-1 py-0.5">{freeInfo.default_model}</code>
                  </p>
                  <a
                    href={freeInfo.key_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    {freeInfo.needs_key ? "Get an API key" : "Provider page"}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </div>
          )}

          <div className="grid gap-2">
            <Label htmlFor="name">Display Name</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={`My ${selectedType?.label || "Provider"}`}
            />
          </div>

          {(providerType === "ollama" || providerType === "custom" || !!freeInfo) && (
            <div className="grid gap-2">
              <Label htmlFor="base-url">Base URL</Label>
              <Input
                id="base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:11434"
              />
              {hasUnfilledTemplate && (
                <p className="text-xs text-destructive">
                  Replace {freeInfo?.template_fields.map((f) => `{${f}}`).join(", ") || "the placeholder"} in
                  the URL with your own value before saving.
                </p>
              )}
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
                  placeholder={isEditMode ? "Enter new key to replace existing" : "sk-..."}
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
          <Button onClick={handleSubmit} disabled={loading || !name || !providerType || hasUnfilledTemplate}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {isEditMode ? "Save Changes" : "Create Provider"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
