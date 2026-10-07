"use client"

import { useState, useEffect, useMemo } from "react"
import dynamic from "next/dynamic"
import "@uiw/react-md-editor/markdown-editor.css"
import { useTheme } from "next-themes"
import { FileText, Plus, Trash2, Search, Loader2, CheckCircle2, Circle, BookOpen, Bot } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { AnimatedList, AnimatedListItem } from "@/components/ui/animated-list"
import { apiClient } from "@/lib/api-client"
import { useConfirm } from "@/hooks/use-confirm"
import type { VaultFile, KnowledgeBase, Agent } from "@/types/playground"

const MDEditor = dynamic(() => import("@uiw/react-md-editor"), { ssr: false })

export default function VaultPage() {
  const { resolvedTheme } = useTheme()
  const [files, setFiles] = useState<VaultFile[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")

  const [activeFile, setActiveFile] = useState<VaultFile | null>(null)
  const [editorContent, setEditorContent] = useState("")
  const [editorName, setEditorName] = useState("")
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const [showUseAsDialog, setShowUseAsDialog] = useState(false)
  const [useAsFile, setUseAsFile] = useState<VaultFile | null>(null)
  const [availableAgents, setAvailableAgents] = useState<Agent[]>([])
  const [availableKBs, setAvailableKBs] = useState<KnowledgeBase[]>([])
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([])
  const [selectedKBId, setSelectedKBId] = useState<string | null>(null)
  const [applyingUseAs, setApplyingUseAs] = useState(false)
  const [ConfirmDeleteDialog, confirmDelete] = useConfirm({
    title: "Delete note",
    description: "This will permanently delete this note. This action cannot be undone.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  useEffect(() => {
    fetchFiles()
  }, [])

  const fetchFiles = async () => {
    setLoading(true)
    try {
      const result = await apiClient.listVaultFiles()
      setFiles(result)
    } catch (e) {
      console.error("Failed to fetch vault files:", e)
    } finally {
      setLoading(false)
    }
  }

  const openFile = (file: VaultFile) => {
    setActiveFile(file)
    setEditorName(file.name)
    setEditorContent(file.content)
    setDirty(false)
  }

  const handleCreate = async () => {
    try {
      const created = await apiClient.createVaultFile({ name: "Untitled note", content: "" })
      setFiles((prev) => [created, ...prev])
      openFile(created)
      toast.success("Note created")
    } catch (e: any) {
      toast.error(e.message || "Failed to create note")
    }
  }

  const handleSave = async () => {
    if (!activeFile) return
    if (!editorName.trim()) {
      toast.error("Name is required")
      return
    }
    setSaving(true)
    try {
      const updated = await apiClient.updateVaultFile(activeFile.id, {
        name: editorName.trim(),
        content: editorContent,
      })
      setFiles((prev) => prev.map((f) => (f.id === updated.id ? updated : f)))
      setActiveFile(updated)
      setDirty(false)
      toast.success("Saved")
    } catch (e: any) {
      toast.error(e.message || "Failed to save note")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (file: VaultFile) => {
    const ok = await confirmDelete()
    if (!ok) return
    try {
      await apiClient.deleteVaultFile(file.id)
      setFiles((prev) => prev.filter((f) => f.id !== file.id))
      if (activeFile?.id === file.id) {
        setActiveFile(null)
        setEditorContent("")
        setEditorName("")
      }
      toast.success("Note deleted")
    } catch (e: any) {
      toast.error(e.message || "Failed to delete note")
    }
  }

  const openUseAsDialog = async (file: VaultFile) => {
    setUseAsFile(file)
    setSelectedAgentIds([])
    setSelectedKBId(null)
    setShowUseAsDialog(true)
    try {
      const [agents, kbs] = await Promise.all([
        apiClient.listAgents(),
        apiClient.listKnowledgeBases(),
      ])
      setAvailableAgents(agents)
      setAvailableKBs(kbs)
    } catch {
      // ignore
    }
  }

  const toggleUseAsAgent = (agentId: string) => {
    setSelectedAgentIds((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId]
    )
  }

  const handleInjectIntoAgents = async () => {
    if (!useAsFile || selectedAgentIds.length === 0) return
    setApplyingUseAs(true)
    try {
      await Promise.all(
        selectedAgentIds.map(async (agentId) => {
          const agent = availableAgents.find((a) => a.id === agentId)
          if (!agent) return
          const nextIds = Array.from(new Set([...(agent.vault_file_ids || []), useAsFile.id]))
          await apiClient.updateAgent(agentId, { vault_file_ids: nextIds })
        })
      )
      toast.success(
        `"${useAsFile.name}" will be injected into ${selectedAgentIds.length} agent${selectedAgentIds.length !== 1 ? "s" : ""}' prompts`
      )
      setShowUseAsDialog(false)
    } catch (e: any) {
      toast.error(e.message || "Failed to attach note to agent(s)")
    } finally {
      setApplyingUseAs(false)
    }
  }

  const handleUseAsKB = async () => {
    if (!useAsFile || !selectedKBId) return
    setApplyingUseAs(true)
    try {
      await apiClient.addKBDocument(selectedKBId, {
        doc_type: "text",
        name: useAsFile.name,
        content_text: useAsFile.content,
      })
      const kbName = availableKBs.find((k) => k.id === selectedKBId)?.name || "knowledge base"
      toast.success(`Copied "${useAsFile.name}" into ${kbName}`)
      setShowUseAsDialog(false)
    } catch (e: any) {
      toast.error(e.message || "Failed to copy note into knowledge base")
    } finally {
      setApplyingUseAs(false)
    }
  }

  const filteredFiles = useMemo(() => {
    if (!searchQuery) return files
    const q = searchQuery.toLowerCase()
    return files.filter((f) => f.name.toLowerCase().includes(q))
  }, [files, searchQuery])

  return (
    <div className="h-full flex overflow-hidden w-full">
      {/* File list sidebar */}
      <div className="w-72 shrink-0 border-r border-border flex flex-col overflow-hidden">
        <div className="p-4 border-b border-border space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <h1 className="text-sm font-medium">Markdown Vault</h1>
              <Badge variant="secondary">{files.length}</Badge>
            </div>
            <Button size="icon-sm" variant="outline" onClick={handleCreate} title="New note">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search notes..."
              className="pl-8 h-8 text-sm"
            />
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : filteredFiles.length === 0 ? (
            <div className="text-center py-8 px-2">
              <p className="text-sm text-muted-foreground">
                {searchQuery ? "No notes match your search" : "No notes yet"}
              </p>
              {!searchQuery && (
                <Button variant="link" size="sm" onClick={handleCreate}>
                  Create your first note
                </Button>
              )}
            </div>
          ) : (
            <AnimatedList className="space-y-1">
              {filteredFiles.map((file) => (
                <AnimatedListItem key={file.id}>
                  <button
                    onClick={() => openFile(file)}
                    className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors group flex items-center justify-between gap-2 ${
                      activeFile?.id === file.id ? "bg-muted font-medium" : "hover:bg-muted/50"
                    }`}
                  >
                    <span className="truncate">{file.name}</span>
                    <Trash2
                      className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive transition-all shrink-0"
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDelete(file)
                      }}
                    />
                  </button>
                </AnimatedListItem>
              ))}
            </AnimatedList>
          )}
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {!activeFile ? (
          <div className="flex-1 flex items-center justify-center text-center p-8">
            <div>
              <FileText className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
              <p className="text-base font-medium">Select a note or create a new one</p>
              <p className="text-sm text-muted-foreground mt-1">
                Write Markdown notes, then use them as prompt context or knowledge base documents for your agents
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="p-4 border-b border-border flex items-center justify-between gap-3 shrink-0">
              <Input
                value={editorName}
                onChange={(e) => {
                  setEditorName(e.target.value)
                  setDirty(true)
                }}
                className="text-base font-medium h-9 max-w-md"
                placeholder="Note name"
              />
              <div className="flex items-center gap-2 shrink-0">
                <Button variant="outline" size="sm" onClick={() => openUseAsDialog(activeFile)}>
                  Use as...
                </Button>
                <Button size="sm" onClick={handleSave} disabled={!dirty || saving}>
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : null}
                  Save
                </Button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto" data-color-mode={resolvedTheme === "dark" ? "dark" : "light"}>
              <MDEditor
                value={editorContent}
                onChange={(v) => {
                  setEditorContent(v || "")
                  setDirty(true)
                }}
                height="100%"
                preview="live"
              />
            </div>
          </>
        )}
      </div>

      {/* Use as dialog */}
      <Dialog open={showUseAsDialog} onOpenChange={setShowUseAsDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Use "{useAsFile?.name}" as...</DialogTitle>
            <DialogDescription>
              Inject this note's full content into an agent's prompt, or copy it into a knowledge base.
            </DialogDescription>
          </DialogHeader>
          <Tabs defaultValue="prompt">
            <TabsList className="w-full">
              <TabsTrigger value="prompt" className="flex-1 gap-1.5">
                <Bot className="h-3.5 w-3.5" />
                Inject into agent prompt
              </TabsTrigger>
              <TabsTrigger value="kb" className="flex-1 gap-1.5">
                <BookOpen className="h-3.5 w-3.5" />
                Knowledge base
              </TabsTrigger>
            </TabsList>
            <TabsContent value="prompt" className="space-y-3">
              <p className="text-xs text-muted-foreground">
                The full note content is appended to the system prompt of selected agents on every turn.
              </p>
              {availableAgents.length === 0 ? (
                <p className="text-xs text-muted-foreground">No agents available.</p>
              ) : (
                <div className="space-y-1 max-h-56 overflow-y-auto rounded-md border border-border p-2">
                  {availableAgents.map((agent) => {
                    const isEnabled = selectedAgentIds.includes(agent.id)
                    return (
                      <button
                        key={agent.id}
                        type="button"
                        onClick={() => toggleUseAsAgent(agent.id)}
                        className="w-full flex items-center gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                      >
                        {isEnabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                        <span className="font-medium">{agent.name}</span>
                      </button>
                    )
                  })}
                </div>
              )}
              <DialogFooter>
                <Button
                  onClick={handleInjectIntoAgents}
                  disabled={selectedAgentIds.length === 0 || applyingUseAs}
                >
                  {applyingUseAs && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
                  Attach to {selectedAgentIds.length || ""} agent{selectedAgentIds.length !== 1 ? "s" : ""}
                </Button>
              </DialogFooter>
            </TabsContent>
            <TabsContent value="kb" className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Copies the current note content into the knowledge base as a text document. Later edits to this note won't update the copy.
              </p>
              {availableKBs.length === 0 ? (
                <p className="text-xs text-muted-foreground">No knowledge bases available.</p>
              ) : (
                <div className="space-y-1 max-h-56 overflow-y-auto rounded-md border border-border p-2">
                  {availableKBs.map((kb) => {
                    const isEnabled = selectedKBId === kb.id
                    return (
                      <button
                        key={kb.id}
                        type="button"
                        onClick={() => setSelectedKBId(kb.id)}
                        className="w-full flex items-center gap-2 p-2 rounded text-xs hover:bg-muted/50 transition-colors text-left"
                      >
                        {isEnabled ? (
                          <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                        ) : (
                          <Circle className="h-4 w-4 text-muted-foreground/50 shrink-0" />
                        )}
                        <span className="font-medium">{kb.name}</span>
                      </button>
                    )
                  })}
                </div>
              )}
              <DialogFooter>
                <Button onClick={handleUseAsKB} disabled={!selectedKBId || applyingUseAs}>
                  {applyingUseAs && <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />}
                  Copy into knowledge base
                </Button>
              </DialogFooter>
            </TabsContent>
          </Tabs>
        </DialogContent>
      </Dialog>
      <ConfirmDeleteDialog />
    </div>
  )
}
