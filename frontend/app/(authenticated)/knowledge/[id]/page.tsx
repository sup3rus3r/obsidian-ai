"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import { useParams, useRouter } from "next/navigation"
import { apiClient } from "@/lib/api-client"
import type { KnowledgeBase, KBDocument, CreateKBDocumentRequest } from "@/types/playground"
import { usePermissionsStore } from "@/stores/permissions-store"
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
import {
  ArrowLeft,
  Trash2,
  FileText,
  Type,
  Upload,
  Plus,
  CheckCircle2,
  Clock,
  Loader2,
  Globe,
} from "lucide-react"
import { toast } from "sonner"
import { useConfirm } from "@/hooks/use-confirm"

type AddMode = "text" | "file" | null

export default function KnowledgeDetailPage() {
  const { data: authSession } = useSession()
  const params = useParams()
  const router = useRouter()
  const kbId = params.id as string

  const canManageKB = usePermissionsStore((s) => s.permissions.create_knowledge_bases)

  const [kb, setKb] = useState<KnowledgeBase | null>(null)
  const [documents, setDocuments] = useState<KBDocument[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [addMode, setAddMode] = useState<AddMode>(null)

  // Text form state
  const [textName, setTextName] = useState("")
  const [textContent, setTextContent] = useState("")
  const [textLoading, setTextLoading] = useState(false)

  // File form state
  const [fileName, setFileName] = useState("")
  const [fileData, setFileData] = useState<string | null>(null)
  const [fileFilename, setFileFilename] = useState<string | null>(null)
  const [fileMediaType, setFileMediaType] = useState<string | null>(null)
  const [fileLoading, setFileLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: "Delete document",
    description: "This will permanently delete this document from the knowledge base.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  useEffect(() => {
    if (!authSession?.accessToken) return
    apiClient.setAccessToken(authSession.accessToken as string)
    load()
  }, [authSession?.accessToken, kbId])

  const load = async () => {
    setIsLoading(true)
    try {
      const [kbData, docs] = await Promise.all([
        apiClient.getKnowledgeBase(kbId),
        apiClient.listKBDocuments(kbId),
      ])
      setKb(kbData)
      setDocuments(docs)
    } catch {
      toast.error("Failed to load knowledge base")
    } finally {
      setIsLoading(false)
    }
  }

  const handleAddText = async () => {
    if (!textName.trim() || !textContent.trim()) return
    setTextLoading(true)
    try {
      const doc = await apiClient.addKBDocument(kbId, {
        doc_type: "text",
        name: textName.trim(),
        content_text: textContent.trim(),
      })
      setDocuments((prev) => [...prev, doc])
      setKb((prev) => prev ? { ...prev, document_count: prev.document_count + 1 } : prev)
      setAddMode(null)
      setTextName("")
      setTextContent("")
      toast.success("Document added and indexed")
    } catch (err: any) {
      toast.error(err?.message || "Failed to add document")
    } finally {
      setTextLoading(false)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileFilename(file.name)
    setFileMediaType(file.type)
    if (!fileName) setFileName(file.name.replace(/\.[^.]+$/, ""))
    const reader = new FileReader()
    reader.onload = (ev) => {
      setFileData(ev.target?.result as string)
    }
    reader.readAsDataURL(file)
  }

  const handleAddFile = async () => {
    if (!fileName.trim() || !fileData || !fileFilename) return
    setFileLoading(true)
    try {
      const doc = await apiClient.addKBDocument(kbId, {
        doc_type: "file",
        name: fileName.trim(),
        file_data: fileData,
        filename: fileFilename,
        media_type: fileMediaType || "application/octet-stream",
      })
      setDocuments((prev) => [...prev, doc])
      setKb((prev) => prev ? { ...prev, document_count: prev.document_count + 1 } : prev)
      setAddMode(null)
      setFileName("")
      setFileData(null)
      setFileFilename(null)
      setFileMediaType(null)
      if (fileInputRef.current) fileInputRef.current.value = ""
      toast.success("File uploaded and indexed")
    } catch (err: any) {
      toast.error(err?.message || "Failed to upload file")
    } finally {
      setFileLoading(false)
    }
  }

  const handleDeleteDoc = async (doc: KBDocument) => {
    const confirmed = await confirmDelete()
    if (!confirmed) return
    try {
      await apiClient.deleteKBDocument(kbId, doc.id)
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id))
      setKb((prev) => prev ? { ...prev, document_count: Math.max(0, prev.document_count - 1) } : prev)
      toast.success("Document deleted")
    } catch (err: any) {
      toast.error(err?.message || "Failed to delete document")
    }
  }

  const handleCloseDialog = () => {
    setAddMode(null)
    setTextName("")
    setTextContent("")
    setFileName("")
    setFileData(null)
    setFileFilename(null)
    setFileMediaType(null)
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!kb) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <p className="text-sm text-muted-foreground">Knowledge base not found.</p>
        <Button variant="outline" size="sm" onClick={() => router.push("/knowledge")}>
          Back to Knowledge Bases
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <ConfirmDialog />

      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-border shrink-0">
        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => router.push("/knowledge")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold truncate">{kb.name}</h1>
            {kb.is_shared && (
              <Badge variant="secondary" className="text-xs gap-1 shrink-0">
                <Globe className="h-3 w-3" />
                Shared
              </Badge>
            )}
          </div>
          {kb.description && (
            <p className="text-xs text-muted-foreground truncate">{kb.description}</p>
          )}
        </div>
        {canManageKB && (
          <div className="flex items-center gap-2 shrink-0">
            <Button variant="outline" size="sm" onClick={() => setAddMode("text")}>
              <Type className="h-4 w-4 mr-1.5" />
              Add Text
            </Button>
            <Button size="sm" onClick={() => setAddMode("file")}>
              <Upload className="h-4 w-4 mr-1.5" />
              Upload File
            </Button>
          </div>
        )}
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-y-auto p-6">
        {documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-60 gap-3 text-center">
            <FileText className="h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No documents yet.</p>
            {canManageKB && (
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => setAddMode("text")}>
                  <Type className="h-4 w-4 mr-1.5" />
                  Add Text
                </Button>
                <Button size="sm" onClick={() => setAddMode("file")}>
                  <Upload className="h-4 w-4 mr-1.5" />
                  Upload File
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className="flex items-center gap-3 px-4 py-3 rounded-md border border-border bg-card hover:bg-muted/30 transition-colors"
              >
                <div className="shrink-0">
                  {doc.doc_type === "text" ? (
                    <Type className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <FileText className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{doc.name}</p>
                  {doc.filename && (
                    <p className="text-xs text-muted-foreground truncate">{doc.filename}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge variant={doc.doc_type === "text" ? "outline" : "secondary"} className="text-xs">
                    {doc.doc_type}
                  </Badge>
                  {doc.indexed ? (
                    <div className="flex items-center gap-1 text-xs text-emerald-600">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      <span>Indexed</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Clock className="h-3.5 w-3.5" />
                      <span>Pending</span>
                    </div>
                  )}
                  {canManageKB && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => handleDeleteDoc(doc)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Text Dialog */}
      <Dialog open={addMode === "text"} onOpenChange={(open) => !open && handleCloseDialog()}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add Text Document</DialogTitle>
            <DialogDescription>
              Paste or type text content. It will be chunked and indexed for RAG.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="text-name">Name</Label>
              <Input
                id="text-name"
                value={textName}
                onChange={(e) => setTextName(e.target.value)}
                placeholder="Document name"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="text-content">Content</Label>
              <Textarea
                id="text-content"
                value={textContent}
                onChange={(e) => setTextContent(e.target.value)}
                placeholder="Paste your text content here..."
                rows={8}
                className="resize-none font-mono text-xs"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={handleCloseDialog}>Cancel</Button>
            <Button
              onClick={handleAddText}
              disabled={textLoading || !textName.trim() || !textContent.trim()}
            >
              {textLoading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Add & Index
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Upload File Dialog */}
      <Dialog open={addMode === "file"} onOpenChange={(open) => !open && handleCloseDialog()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Upload File</DialogTitle>
            <DialogDescription>
              Upload a PDF, DOCX, TXT, or Markdown file. Text will be extracted and indexed.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="file-input">File</Label>
              <input
                ref={fileInputRef}
                id="file-input"
                type="file"
                accept=".pdf,.docx,.txt,.md,.markdown"
                onChange={handleFileChange}
                className="block w-full text-sm text-muted-foreground file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border file:border-border file:text-xs file:font-medium file:bg-background hover:file:bg-muted cursor-pointer"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="file-name">Display Name</Label>
              <Input
                id="file-name"
                value={fileName}
                onChange={(e) => setFileName(e.target.value)}
                placeholder="Document name"
              />
            </div>
            {fileFilename && (
              <p className="text-xs text-muted-foreground">
                Selected: <span className="font-medium">{fileFilename}</span>
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={handleCloseDialog}>Cancel</Button>
            <Button
              onClick={handleAddFile}
              disabled={fileLoading || !fileName.trim() || !fileData}
            >
              {fileLoading && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              Upload & Index
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
