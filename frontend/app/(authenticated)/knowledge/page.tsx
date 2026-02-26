"use client"

import { useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import { apiClient } from "@/lib/api-client"
import type { KnowledgeBase, CreateKnowledgeBaseRequest } from "@/types/playground"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { BookOpen, Plus, Trash2, FileText, Globe, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { useConfirm } from "@/hooks/use-confirm"
import { usePermissionsStore } from "@/stores/permissions-store"

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleDateString()
}

export default function KnowledgePage() {
  const { data: authSession } = useSession()
  const router = useRouter()
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [createName, setCreateName] = useState("")
  const [createDescription, setCreateDescription] = useState("")
  const [createShared, setCreateShared] = useState(false)
  const [createLoading, setCreateLoading] = useState(false)
  const userRole = (authSession?.user as { role?: string })?.role
  const canCreateKB = usePermissionsStore((s) => s.permissions.create_knowledge_bases)

  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: "Delete knowledge base",
    description: "This will permanently delete this knowledge base and all its documents. This action cannot be undone.",
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
      const kbs = await apiClient.listKnowledgeBases()
      setKnowledgeBases(kbs)
    } catch {
      toast.error("Failed to load knowledge bases")
    } finally {
      setIsLoading(false)
    }
  }

  const handleCreate = async () => {
    if (!createName.trim()) return
    setCreateLoading(true)
    try {
      const kb = await apiClient.createKnowledgeBase({
        name: createName.trim(),
        description: createDescription.trim() || undefined,
        is_shared: createShared,
      })
      setKnowledgeBases((prev) => [kb, ...prev])
      setShowCreateDialog(false)
      setCreateName("")
      setCreateDescription("")
      setCreateShared(false)
      toast.success("Knowledge base created")
      router.push(`/knowledge/${kb.id}`)
    } catch (err: any) {
      toast.error(err?.message || "Failed to create knowledge base")
    } finally {
      setCreateLoading(false)
    }
  }

  const handleDelete = async (kb: KnowledgeBase) => {
    const confirmed = await confirmDelete()
    if (!confirmed) return
    try {
      await apiClient.deleteKnowledgeBase(kb.id)
      setKnowledgeBases((prev) => prev.filter((k) => k.id !== kb.id))
      toast.success("Knowledge base deleted")
    } catch (err: any) {
      toast.error(err?.message || "Failed to delete knowledge base")
    }
  }

  const handleDialogClose = (open: boolean) => {
    if (!open) {
      setCreateName("")
      setCreateDescription("")
      setCreateShared(false)
    }
    setShowCreateDialog(open)
  }

  return (
    <div className="flex flex-col h-full">
      <ConfirmDialog />

      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-lg font-semibold">Knowledge Bases</h1>
        </div>
        {canCreateKB && (
          <Button size="sm" className="h-9" onClick={() => setShowCreateDialog(true)}>
            <Plus className="h-4 w-4 mr-1.5" />
            New Knowledge Base
          </Button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center h-40">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : knowledgeBases.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-60 gap-3 text-center">
            <BookOpen className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No knowledge bases yet.</p>
            <Button size="sm" variant="outline" className="h-13" onClick={() => setShowCreateDialog(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              Create your first knowledge base
            </Button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {knowledgeBases.map((kb) => (
              <Card
                key={kb.id}
                className="cursor-pointer hover:bg-muted/30 transition-colors"
                onClick={() => router.push(`/knowledge/${kb.id}`)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-sm font-medium leading-snug">{kb.name}</CardTitle>
                    <div className="flex items-center gap-1 shrink-0">
                      {kb.is_shared && (
                        <Badge variant="secondary" className="text-xs gap-1">
                          <Globe className="h-3 w-3" />
                          Shared
                        </Badge>
                      )}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  {kb.description && (
                    <p className="text-xs text-muted-foreground mb-3 line-clamp-2">{kb.description}</p>
                  )}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <FileText className="h-3.5 w-3.5" />
                      <span>{kb.document_count} document{kb.document_count !== 1 ? "s" : ""}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-xs text-muted-foreground">{formatDate(kb.created_at)}</span>
                      {canCreateKB && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(kb)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={handleDialogClose}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create Knowledge Base</DialogTitle>
            <DialogDescription>
              A knowledge base stores documents and text that agents can query using RAG.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="kb-name">Name</Label>
              <Input
                id="kb-name"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="My Knowledge Base"
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="kb-description">Description</Label>
              <Textarea
                id="kb-description"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                placeholder="Describe what this knowledge base contains..."
                rows={3}
                className="resize-none"
              />
            </div>
            {userRole === "admin" && (
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="kb-shared"
                  checked={createShared}
                  onChange={(e) => setCreateShared(e.target.checked)}
                  className="h-4 w-4 rounded border-border"
                />
                <Label htmlFor="kb-shared" className="cursor-pointer">
                  Share with all users
                </Label>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCreateDialog(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={createLoading || !createName.trim()}>
              {createLoading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
