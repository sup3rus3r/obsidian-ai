"use client"

import { usePlaygroundStore } from "@/stores/playground-store"
import { Badge } from "@/components/ui/badge"
import { Plus, Trash2, Download, Upload, DownloadCloud, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useState } from "react"
import { SidebarSection } from "./sidebar-section"
import { useConfirm } from "@/hooks/use-confirm"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface EndpointConfigProps {
  onAddProvider?: () => void
  onEditProvider?: (providerId: string) => void
  onExportProvider?: (providerId: string, providerName: string) => void
  onImportProvider?: () => void
  onExportAllProviders?: () => void
  hideAdd?: boolean
}

export function EndpointConfig({
  onAddProvider,
  onEditProvider,
  onExportProvider,
  onImportProvider,
  onExportAllProviders,
  hideAdd,
}: EndpointConfigProps) {
  const providers = usePlaygroundStore((s) => s.providers)
  const selectedProviderId = usePlaygroundStore((s) => s.selectedProviderId)
  const setSelectedProvider = usePlaygroundStore((s) => s.setSelectedProvider)
  const deleteProvider = usePlaygroundStore((s) => s.deleteProvider)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [ConfirmDialog, confirmDelete] = useConfirm({
    title: "Delete provider",
    description: "This will permanently delete this provider configuration.",
    confirmLabel: "Delete",
    variant: "destructive",
  })

  const handleDelete = async (e: React.MouseEvent, providerId: string) => {
    e.stopPropagation()
    const ok = await confirmDelete()
    if (!ok) return
    setDeletingId(providerId)
    try {
      await deleteProvider(providerId)
    } finally {
      setDeletingId(null)
    }
  }

  const headerActions = (
    <div className="flex items-center gap-0.5">
      {onImportProvider && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="h-6 w-6" onClick={onImportProvider}>
              <Upload className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">Import provider from JSON</TooltipContent>
        </Tooltip>
      )}
      {onExportAllProviders && providers.length > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="h-6 w-6" onClick={onExportAllProviders}>
              <DownloadCloud className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">Export all providers</TooltipContent>
        </Tooltip>
      )}
      {!hideAdd && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" className="h-6 w-6" onClick={onAddProvider}>
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">Add provider</TooltipContent>
        </Tooltip>
      )}
    </div>
  )

  return (
    <>
    <SidebarSection title="Endpoints" action={headerActions}>
      {providers.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No providers configured. Create a provider to get started.
        </p>
      ) : (
        <div className="space-y-1">
          {providers.map((provider) => (
            <div
              key={provider.id}
              className={`flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors group ${
                selectedProviderId === provider.id
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "hover:bg-sidebar-accent/50"
              }`}
            >
              <button
                onClick={() => setSelectedProvider(provider.id)}
                className="flex-1 flex items-center gap-2 min-w-0 text-left text-sm"
              >
                <span
                  className={`h-2 w-2 rounded-full flex-shrink-0 ${
                    provider.is_active ? "bg-emerald-500" : "bg-red-500"
                  }`}
                />
                <span className="truncate flex-1">{provider.name}</span>
                <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                  {provider.provider_type}
                </Badge>
              </button>
              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                {onEditProvider && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6"
                    onClick={(e) => {
                      e.stopPropagation()
                      onEditProvider(provider.id)
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                )}
                {onExportProvider && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="h-6 w-6"
                    onClick={(e) => {
                      e.stopPropagation()
                      onExportProvider(provider.id, provider.name)
                    }}
                  >
                    <Download className="h-3.5 w-3.5" />
                  </Button>
                )}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  className="h-6 w-6"
                  onClick={(e) => handleDelete(e, provider.id)}
                  disabled={deletingId === provider.id}
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </SidebarSection>
    <ConfirmDialog />
    </>
  )
}
