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
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { apiClient } from "@/lib/api-client"
import { usePlaygroundStore } from "@/stores/playground-store"
import type { MCPServer } from "@/types/playground"
import { Loader2, CheckCircle2, XCircle, Terminal, Globe } from "lucide-react"

interface MCPServerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  server?: MCPServer | null
  onSaved?: (server: MCPServer) => void
}

export function MCPServerDialog({ open, onOpenChange, server, onSaved }: MCPServerDialogProps) {
  const mcpServers = usePlaygroundStore((s) => s.mcpServers)
  const setMCPServers = usePlaygroundStore((s) => s.setMCPServers)

  const isEditing = !!server

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [transportType, setTransportType] = useState<"stdio" | "sse">("stdio")
  // stdio fields
  const [command, setCommand] = useState("")
  const [argsText, setArgsText] = useState("")
  const [envText, setEnvText] = useState("")
  // sse fields
  const [url, setUrl] = useState("")
  const [headersText, setHeadersText] = useState("")

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  useEffect(() => {
    if (!open) return
    if (server) {
      setName(server.name)
      setDescription(server.description || "")
      setTransportType(server.transport_type)
      setCommand(server.command || "")
      setArgsText(server.args?.join(", ") || "")
      setEnvText(
        server.env
          ? Object.entries(server.env)
              .map(([k, v]) => `${k}=${v}`)
              .join("\n")
          : ""
      )
      setUrl(server.url || "")
      setHeadersText(
        server.headers
          ? Object.entries(server.headers)
              .map(([k, v]) => `${k}: ${v}`)
              .join("\n")
          : ""
      )
      setTestResult(null)
    } else {
      resetForm()
    }
  }, [open, server])

  const parseArgs = (): string[] | undefined => {
    const trimmed = argsText.trim()
    if (!trimmed) return undefined
    return trimmed.split(",").map((s) => s.trim()).filter(Boolean)
  }

  const parseEnv = (): Record<string, string> | undefined => {
    const trimmed = envText.trim()
    if (!trimmed) return undefined
    const result: Record<string, string> = {}
    for (const line of trimmed.split("\n")) {
      const idx = line.indexOf("=")
      if (idx > 0) {
        result[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
      }
    }
    return Object.keys(result).length > 0 ? result : undefined
  }

  const parseHeaders = (): Record<string, string> | undefined => {
    const trimmed = headersText.trim()
    if (!trimmed) return undefined
    const result: Record<string, string> = {}
    for (const line of trimmed.split("\n")) {
      const idx = line.indexOf(":")
      if (idx > 0) {
        result[line.slice(0, idx).trim()] = line.slice(idx + 1).trim()
      }
    }
    return Object.keys(result).length > 0 ? result : undefined
  }

  const handleSave = async () => {
    if (!name) return
    setError("")
    setLoading(true)
    try {
      const payload = {
        name,
        description: description || undefined,
        transport_type: transportType,
        ...(transportType === "stdio"
          ? { command, args: parseArgs(), env: parseEnv() }
          : { url, headers: parseHeaders() }),
      }

      if (isEditing && server) {
        const updated = await apiClient.updateMCPServer(server.id, payload)
        setMCPServers(mcpServers.map((s) => (s.id === updated.id ? updated : s)))
        onSaved?.(updated)
      } else {
        const created = await apiClient.createMCPServer(payload as any)
        setMCPServers([...mcpServers, created])
        onSaved?.(created)
      }
      resetForm()
      onOpenChange(false)
    } catch (err: any) {
      console.error("Failed to save MCP server:", err)
      setError(err?.message || "Failed to save MCP server")
    } finally {
      setLoading(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      let result: { success: boolean; tools_count: number; error?: string }
      if (isEditing && server) {
        result = await apiClient.testMCPServer(server.id)
      } else {
        const config = {
          name: name || "test",
          transport_type: transportType,
          ...(transportType === "stdio"
            ? { command, args: parseArgs(), env: parseEnv() }
            : { url, headers: parseHeaders() }),
        }
        result = await apiClient.testMCPConfig(config)
      }
      if (result.success) {
        setTestResult({
          success: true,
          message: `Connected successfully. Found ${result.tools_count} tool(s).`,
        })
      } else {
        setTestResult({
          success: false,
          message: result.error || "Connection failed",
        })
      }
    } catch (err) {
      setTestResult({ success: false, message: "Failed to test connection" })
    } finally {
      setTesting(false)
    }
  }

  const resetForm = () => {
    setName("")
    setDescription("")
    setTransportType("stdio")
    setCommand("")
    setArgsText("")
    setEnvText("")
    setUrl("")
    setHeadersText("")
    setTestResult(null)
    setError("")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEditing ? "Edit MCP Server" : "Add MCP Server"}</DialogTitle>
          <DialogDescription>
            {isEditing
              ? "Update the MCP server configuration."
              : "Connect to an MCP server to discover and use its tools."}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="mcp-name">Name</Label>
            <Input
              id="mcp-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-mcp-server"
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="mcp-desc">Description</Label>
            <Input
              id="mcp-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What tools does this server provide?"
            />
          </div>

          <div className="grid gap-2">
            <Label>Transport</Label>
            <Select
              value={transportType}
              onValueChange={(v) => setTransportType(v as "stdio" | "sse")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stdio">
                  <span className="flex items-center gap-2">
                    <Terminal className="h-3.5 w-3.5" />
                    Stdio (local process)
                  </span>
                </SelectItem>
                <SelectItem value="sse">
                  <span className="flex items-center gap-2">
                    <Globe className="h-3.5 w-3.5" />
                    SSE (remote HTTP)
                  </span>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>

          {transportType === "stdio" ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="mcp-command">Command</Label>
                <Input
                  id="mcp-command"
                  value={command}
                  onChange={(e) => setCommand(e.target.value)}
                  placeholder="npx, python, uvx, etc."
                  className="font-mono text-sm"
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="mcp-args">
                  Arguments{" "}
                  <span className="text-muted-foreground font-normal">(comma-separated)</span>
                </Label>
                <Input
                  id="mcp-args"
                  value={argsText}
                  onChange={(e) => setArgsText(e.target.value)}
                  placeholder="-m, my_server, --port, 3000"
                  className="font-mono text-sm"
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="mcp-env">
                  Environment Variables{" "}
                  <span className="text-muted-foreground font-normal">(KEY=VALUE per line)</span>
                </Label>
                <Textarea
                  id="mcp-env"
                  value={envText}
                  onChange={(e) => setEnvText(e.target.value)}
                  placeholder={"API_KEY=sk-...\nDEBUG=true"}
                  rows={3}
                  className="font-mono text-xs resize-none"
                />
              </div>
            </>
          ) : (
            <>
              <div className="grid gap-2">
                <Label htmlFor="mcp-url">URL</Label>
                <Input
                  id="mcp-url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="http://localhost:8080/sse"
                  className="font-mono text-sm"
                />
              </div>

              <div className="grid gap-2">
                <Label htmlFor="mcp-headers">
                  Headers{" "}
                  <span className="text-muted-foreground font-normal">(Key: Value per line)</span>
                </Label>
                <Textarea
                  id="mcp-headers"
                  value={headersText}
                  onChange={(e) => setHeadersText(e.target.value)}
                  placeholder={"Authorization: Bearer sk-...\nX-Custom: value"}
                  rows={3}
                  className="font-mono text-xs resize-none"
                />
              </div>
            </>
          )}

          {/* Test result */}
          {testResult && (
            <div
              className={`flex items-start gap-2 p-3 rounded-md text-xs ${
                testResult.success
                  ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                  : "bg-destructive/10 text-destructive"
              }`}
            >
              {testResult.success ? (
                <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
              ) : (
                <XCircle className="h-4 w-4 shrink-0 mt-0.5" />
              )}
              <span>{testResult.message}</span>
            </div>
          )}
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            variant="outline"
            onClick={handleTest}
            disabled={testing || (transportType === "stdio" ? !command : !url)}
            className="mr-auto"
          >
            {testing ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            Test Connection
          </Button>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={loading || !name}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {isEditing ? "Save Changes" : "Add Server"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
