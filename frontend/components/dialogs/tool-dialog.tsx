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
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiClient } from "@/lib/api-client"
import { Switch } from "@/components/ui/switch"
import {
  Loader2,
  ArrowLeft,
  Plus,
  Cloud,
  Calculator,
  Search,
  Clock,
  Globe,
  Code,
  Sparkles,
  ShieldAlert,
} from "lucide-react"

interface ToolDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  initialTool?: import("@/types/playground").ToolDefinition
}

interface ToolTemplate {
  id: string
  name: string
  label: string
  description: string
  icon: React.ElementType
  handlerType: "http" | "python" | "builtin"
  parameters: string
  handlerConfig: string
}

const TEMPLATES: ToolTemplate[] = [
  {
    id: "weather",
    name: "get_weather",
    label: "Weather Lookup",
    description: "Get the current weather for any location",
    icon: Cloud,
    handlerType: "python",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          location: {
            type: "string",
            description: "The city or location to get weather for",
          },
        },
        required: ["location"],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        code: "def handler(params):\n    import urllib.request, json\n    location = params.get('location', 'London')\n    # Step 1: Geocode the location using Open-Meteo geocoding API\n    geo_url = f'https://geocoding-api.open-meteo.com/v1/search?name={urllib.request.quote(location)}&count=1&language=en&format=json'\n    with urllib.request.urlopen(geo_url) as r:\n        geo = json.loads(r.read())\n    if not geo.get('results'):\n        return {'error': f'Location not found: {location}'}\n    result = geo['results'][0]\n    lat, lon = result['latitude'], result['longitude']\n    name = result.get('name', location)\n    country = result.get('country', '')\n    # Step 2: Fetch weather from Open-Meteo\n    wx_url = (f'https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}'\n              '&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code'\n              '&temperature_unit=celsius&wind_speed_unit=kmh&timezone=auto')\n    with urllib.request.urlopen(wx_url) as r:\n        wx = json.loads(r.read())\n    cur = wx['current']\n    wmo = {0:'Clear sky',1:'Mainly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Icy fog',51:'Light drizzle',53:'Moderate drizzle',55:'Dense drizzle',61:'Slight rain',63:'Moderate rain',65:'Heavy rain',71:'Slight snow',73:'Moderate snow',75:'Heavy snow',80:'Slight showers',81:'Moderate showers',82:'Violent showers',95:'Thunderstorm',96:'Thunderstorm w/ hail',99:'Thunderstorm w/ heavy hail'}\n    code = cur.get('weather_code', 0)\n    condition = wmo.get(code, f'Code {code}')\n    temp_c = cur['temperature_2m']\n    temp_f = round(temp_c * 9/5 + 32, 1)\n    return {\n        'location': f'{name}, {country}',\n        'temperature_c': temp_c,\n        'temperature_f': temp_f,\n        'humidity_pct': cur['relative_humidity_2m'],\n        'wind_kmh': cur['wind_speed_10m'],\n        'condition': condition,\n    }",
      },
      null,
      2,
    ),
  },
  {
    id: "calculator",
    name: "calculator",
    label: "Calculator",
    description: "Evaluate mathematical expressions",
    icon: Calculator,
    handlerType: "python",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          expression: {
            type: "string",
            description: "The math expression to evaluate (e.g. '2 + 2 * 3')",
          },
        },
        required: ["expression"],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        code: "def handler(params):\n    import ast\n    expr = params.get('expression', '')\n    result = eval(compile(ast.parse(expr, mode='eval'), '<expr>', 'eval'))\n    return {'result': str(result)}",
      },
      null,
      2,
    ),
  },
  {
    id: "web_search",
    name: "web_search",
    label: "Web Search",
    description: "Search the web for information",
    icon: Search,
    handlerType: "python",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "The search query",
          },
          limit: {
            type: "integer",
            description: "Maximum number of results",
            default: 5,
          },
        },
        required: ["query"],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        code: "def handler(params):\n    import urllib.request, urllib.parse, json, html, re\n    query = params.get('query', '')\n    limit = int(params.get('limit', 5))\n    if not query:\n        return {'error': 'query is required'}\n    # DuckDuckGo Instant Answer API (no key required)\n    ia_url = 'https://api.duckduckgo.com/?' + urllib.parse.urlencode({'q': query, 'format': 'json', 'no_html': 1, 'skip_disambig': 1})\n    req = urllib.request.Request(ia_url, headers={'User-Agent': 'Mozilla/5.0'})\n    with urllib.request.urlopen(req, timeout=10) as r:\n        data = json.loads(r.read())\n    results = []\n    # Abstract (Wikipedia-style summary)\n    if data.get('AbstractText'):\n        results.append({'title': data.get('Heading', query), 'snippet': data['AbstractText'], 'url': data.get('AbstractURL', '')})\n    # Related topics\n    for topic in data.get('RelatedTopics', [])[:limit]:\n        if isinstance(topic, dict) and topic.get('Text'):\n            results.append({'title': topic.get('Text', '')[:80], 'snippet': topic.get('Text', ''), 'url': topic.get('FirstURL', '')})\n        if len(results) >= limit:\n            break\n    # Answer (e.g. calculator results)\n    if not results and data.get('Answer'):\n        results.append({'title': 'Answer', 'snippet': str(data['Answer']), 'url': ''})\n    if not results:\n        return {'query': query, 'results': [], 'note': 'No instant-answer results. Try a more specific query.'}\n    return {'query': query, 'results': results[:limit]}",
      },
      null,
      2,
    ),
  },
  {
    id: "datetime",
    name: "get_datetime",
    label: "Date & Time",
    description: "Get the current date and time",
    icon: Clock,
    handlerType: "python",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          timezone: {
            type: "string",
            description: "Timezone (e.g. 'UTC', 'US/Eastern')",
            default: "UTC",
          },
        },
        required: [],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        code: "def handler(params):\n    from datetime import datetime, timezone\n    tz = params.get('timezone', 'UTC')\n    now = datetime.now(timezone.utc)\n    return {'datetime': now.isoformat(), 'timezone': tz}",
      },
      null,
      2,
    ),
  },
  {
    id: "http_request",
    name: "http_request",
    label: "API Request",
    description: "Call any external REST API endpoint",
    icon: Globe,
    handlerType: "http",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "The input to send to the API",
          },
        },
        required: ["query"],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        url: "https://api.example.com/endpoint",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      },
      null,
      2,
    ),
  },
  {
    id: "custom_python",
    name: "custom_function",
    label: "Custom Python",
    description: "Write your own Python handler function",
    icon: Code,
    handlerType: "python",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          input: {
            type: "string",
            description: "The input to process",
          },
        },
        required: ["input"],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        code: "def handler(params):\n    input_val = params.get('input', '')\n    # Your custom logic here\n    return {'result': f'Processed: {input_val}'}",
      },
      null,
      2,
    ),
  },
  {
    id: "generative_ui",
    name: "render_ui",
    label: "Generative UI",
    description: "Returns structured data rendered as a rich UI card",
    icon: Sparkles,
    handlerType: "python",
    parameters: JSON.stringify(
      {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Text to analyze",
          },
        },
        required: ["query"],
      },
      null,
      2,
    ),
    handlerConfig: JSON.stringify(
      {
        code: "def handler(params):\n    query = params.get('query', '')\n    words = len(query.split())\n    chars = len(query)\n    # Return a stat card — the UI will render this as a rich component.\n    # Supported _ui_type: 'stat' (title, value, label)\n    return {\n        '_ui_type': 'stat',\n        'title': 'Text Analysis',\n        'value': f'{words} word{\"s\" if words != 1 else \"\"}',\n        'label': f'{chars} character{\"s\" if chars != 1 else \"\"} · rendered as a generative UI card',\n    }",
      },
      null,
      2,
    ),
  },
]

export function ToolDialog({ open, onOpenChange, initialTool }: ToolDialogProps) {
  const isEditing = !!initialTool
  const [view, setView] = useState<"pick" | "form">(isEditing ? "form" : "pick")
  const [name, setName] = useState(initialTool?.name ?? "")
  const [description, setDescription] = useState(initialTool?.description ?? "")
  const [handlerType, setHandlerType] = useState(initialTool?.handler_type ?? "python")
  const [parametersJson, setParametersJson] = useState(
    initialTool ? JSON.stringify(initialTool.parameters, null, 2) : ""
  )
  const [handlerConfigJson, setHandlerConfigJson] = useState(
    initialTool?.handler_config ? JSON.stringify(initialTool.handler_config, null, 2) : ""
  )
  const [requiresConfirmation, setRequiresConfirmation] = useState(initialTool?.requires_confirmation ?? false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  // Sync form state when initialTool changes (e.g. opening edit for a different tool)
  useEffect(() => {
    if (initialTool) {
      setView("form")
      setName(initialTool.name)
      setDescription(initialTool.description ?? "")
      setHandlerType(initialTool.handler_type)
      setParametersJson(JSON.stringify(initialTool.parameters, null, 2))
      setHandlerConfigJson(initialTool.handler_config ? JSON.stringify(initialTool.handler_config, null, 2) : "")
      setRequiresConfirmation(initialTool.requires_confirmation ?? false)
      setError("")
    } else {
      setView("pick")
    }
  }, [initialTool])

  const handlePickTemplate = (template: ToolTemplate) => {
    setName(template.name)
    setDescription(template.description)
    setHandlerType(template.handlerType)
    setParametersJson(template.parameters)
    setHandlerConfigJson(template.handlerConfig)
    setRequiresConfirmation(false)
    setError("")
    setView("form")
  }

  const handleStartBlank = () => {
    setName("")
    setDescription("")
    setHandlerType("python")
    setParametersJson(
      JSON.stringify(
        {
          type: "object",
          properties: {
            input: { type: "string", description: "The input" },
          },
          required: ["input"],
        },
        null,
        2,
      ),
    )
    setHandlerConfigJson(
      JSON.stringify(
        {
          code: "def handler(params):\n    return {'result': 'hello'}",
        },
        null,
        2,
      ),
    )
    setRequiresConfirmation(false)
    setError("")
    setView("form")
  }

  const handleHandlerTypeChange = (type: string) => {
    setHandlerType(type)
    if (type === "http") {
      setHandlerConfigJson(
        JSON.stringify(
          {
            url: "https://api.example.com/endpoint",
            method: "POST",
            headers: { "Content-Type": "application/json" },
          },
          null,
          2,
        ),
      )
    } else if (type === "python") {
      setHandlerConfigJson(
        JSON.stringify(
          {
            code: "def handler(params):\n    return {'result': 'hello'}",
          },
          null,
          2,
        ),
      )
    }
  }

  const parseFields = (): { parameters: Record<string, unknown>; handlerConfig: Record<string, unknown> | undefined } | null => {
    let parameters: Record<string, unknown>
    let handlerConfig: Record<string, unknown> | undefined
    try {
      parameters = JSON.parse(parametersJson)
    } catch {
      setError("Invalid JSON in parameters schema")
      return null
    }
    try {
      handlerConfig = handlerConfigJson.trim() ? JSON.parse(handlerConfigJson) : undefined
    } catch {
      setError("Invalid JSON in handler config")
      return null
    }
    return { parameters, handlerConfig }
  }

  const handleCreate = async () => {
    if (!name) return
    setError("")
    const parsed = parseFields()
    if (!parsed) return
    setLoading(true)
    try {
      await apiClient.createTool({
        name,
        description: description || undefined,
        parameters: parsed.parameters,
        handler_type: handlerType,
        handler_config: parsed.handlerConfig,
        requires_confirmation: requiresConfirmation,
      })
      window.dispatchEvent(new CustomEvent("tool-created"))
      resetAndClose()
    } catch (err: any) {
      console.error("Failed to create tool:", err)
      setError(err?.message || "Failed to create tool")
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    if (!name || !initialTool) return
    setError("")
    const parsed = parseFields()
    if (!parsed) return
    setLoading(true)
    try {
      await apiClient.updateTool(initialTool.id, {
        name,
        description: description || undefined,
        parameters: parsed.parameters,
        handler_type: handlerType,
        handler_config: parsed.handlerConfig,
        requires_confirmation: requiresConfirmation,
      })
      window.dispatchEvent(new CustomEvent("tool-updated"))
      resetAndClose()
    } catch (err: any) {
      console.error("Failed to update tool:", err)
      setError(err?.message || "Failed to save tool")
    } finally {
      setLoading(false)
    }
  }

  const resetAndClose = () => {
    setName("")
    setDescription("")
    setHandlerType("python")
    setParametersJson("")
    setHandlerConfigJson("")
    setRequiresConfirmation(false)
    setError("")
    if (!isEditing) setView("pick")
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          if (!isEditing) setView("pick")
          setError("")
        }
        onOpenChange(o)
      }}
    >
      <DialogContent className="sm:max-w-2xl overflow-hidden">
        {view === "pick" ? (
          <>
            <DialogHeader>
              <DialogTitle>Create a Tool</DialogTitle>
              <DialogDescription>
                Pick a template to get started or create one from scratch.
              </DialogDescription>
            </DialogHeader>

            <div className="grid grid-cols-2 gap-2 py-2 max-h-[60vh] overflow-y-auto pr-1">
              {TEMPLATES.map((t) => (
                <button
                  key={t.id}
                  onClick={() => handlePickTemplate(t)}
                  className="flex items-start gap-3 p-3 rounded-lg border border-border bg-card text-left transition-colors hover:bg-accent hover:border-accent-foreground/20"
                >
                  <div className="mt-0.5 rounded-md bg-muted p-1.5">
                    <t.icon className="h-4 w-4 text-muted-foreground" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium">{t.label}</div>
                    <div className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {t.description}
                    </div>
                  </div>
                </button>
              ))}
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button variant="secondary" onClick={handleStartBlank}>
                <Plus className="h-3.5 w-3.5 mr-1.5" />
                Blank Tool
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <div className="flex items-center gap-2">
                {!isEditing && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6 shrink-0"
                    onClick={() => setView("pick")}
                  >
                    <ArrowLeft className="h-3.5 w-3.5" />
                  </Button>
                )}
                <div>
                  <DialogTitle>{isEditing ? "Edit Tool" : "Configure Tool"}</DialogTitle>
                  <DialogDescription>
                    {isEditing
                      ? "Update the tool name, parameters, and handler."
                      : "Customize the tool name, parameters, and handler."}
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>

            <div className="grid gap-4 py-2 max-h-[60vh] overflow-y-auto pr-1">
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-1.5">
                  <Label htmlFor="tool-name">Name</Label>
                  <Input
                    id="tool-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="my_tool"
                    className="font-mono text-sm"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="tool-handler-type">Handler Type</Label>
                  <Select
                    value={handlerType}
                    onValueChange={handleHandlerTypeChange}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="python">Python (code)</SelectItem>
                      <SelectItem value="http">HTTP (API call)</SelectItem>
                      <SelectItem value="builtin">Built-in</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="tool-desc">Description</Label>
                <Input
                  id="tool-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe what this tool does — the agent reads this"
                />
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="tool-params">
                  Parameters{" "}
                  <span className="text-muted-foreground font-normal">
                    (JSON Schema)
                  </span>
                </Label>
                <Textarea
                  id="tool-params"
                  value={parametersJson}
                  onChange={(e) => setParametersJson(e.target.value)}
                  rows={7}
                  className="font-mono text-xs resize-none"
                />
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="tool-config">
                  Handler Config{" "}
                  <span className="text-muted-foreground font-normal">
                    (
                    {handlerType === "http"
                      ? "url, method, headers"
                      : handlerType === "python"
                        ? "code"
                        : "config"}
                    )
                  </span>
                </Label>
                <Textarea
                  id="tool-config"
                  value={handlerConfigJson}
                  onChange={(e) => setHandlerConfigJson(e.target.value)}
                  rows={7}
                  className="font-mono text-xs resize-none"
                />
              </div>

              {/* Requires human confirmation toggle */}
              <div className="flex items-start gap-3 rounded-lg border border-border p-3">
                <ShieldAlert className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">Requires human approval</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    When enabled, the agent will pause and ask for approval before executing this tool.
                  </div>
                </div>
                <Switch
                  checked={requiresConfirmation}
                  onCheckedChange={setRequiresConfirmation}
                />
              </div>

              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={isEditing ? handleSave : handleCreate} disabled={loading || !name}>
                {loading ? (
                  <Loader2 className="h-5 w-4 animate-spin mr-2" />
                ) : null}
                {isEditing ? "Save Changes" : "Create Tool"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
