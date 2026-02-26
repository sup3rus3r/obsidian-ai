"use client"

import { useState, useCallback } from "react"
import {
  ChevronRight,
  File as FileIcon,
  Folder as FolderIcon,
  FolderOpen as FolderOpenIcon,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { FileNode } from "@/types/playground"

interface FileTreeNodeProps {
  node: FileNode
  depth: number
  expandedPaths: Set<string>
  selectedPath?: string
  onToggle: (path: string) => void
  onSelect?: (path: string) => void
}

function FileTreeNode({
  node,
  depth,
  expandedPaths,
  selectedPath,
  onToggle,
  onSelect,
}: FileTreeNodeProps) {
  const isExpanded = expandedPaths.has(node.path)
  const isSelected = selectedPath === node.path
  const isDirectory = node.type === "directory"
  const hasChildren = isDirectory && node.children && node.children.length > 0

  const handleClick = useCallback(() => {
    if (isDirectory) {
      onToggle(node.path)
    }
    onSelect?.(node.path)
  }, [isDirectory, node.path, onToggle, onSelect])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault()
        handleClick()
      }
    },
    [handleClick]
  )

  return (
    <div>
      <div
        role={isDirectory ? "treeitem" : "treeitem"}
        aria-expanded={isDirectory ? isExpanded : undefined}
        tabIndex={0}
        className={cn(
          "flex items-center gap-1.5 rounded px-2 py-1 text-sm cursor-pointer select-none transition-colors",
          "hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          isSelected && "bg-muted"
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
      >
        {/* Chevron for directories */}
        {isDirectory ? (
          <ChevronRight
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-150",
              isExpanded && "rotate-90"
            )}
          />
        ) : (
          <span className="h-3.5 w-3.5 shrink-0" /> // spacer to align with folders
        )}

        {/* Icon */}
        {isDirectory ? (
          isExpanded ? (
            <FolderOpenIcon className="h-4 w-4 shrink-0 text-blue-500" />
          ) : (
            <FolderIcon className="h-4 w-4 shrink-0 text-blue-500" />
          )
        ) : (
          <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}

        {/* Name */}
        <span className="truncate font-mono text-xs">{node.name}</span>
      </div>

      {/* Children */}
      {isDirectory && isExpanded && hasChildren && (
        <div className="border-l border-border ml-4">
          {node.children!.map((child) => (
            <FileTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              expandedPaths={expandedPaths}
              selectedPath={selectedPath}
              onToggle={onToggle}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface FileTreeProps {
  nodes: FileNode[]
  onSelect?: (path: string) => void
  className?: string
}

export function FileTree({ nodes, onSelect, className }: FileTreeProps) {
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set())
  const [selectedPath, setSelectedPath] = useState<string | undefined>()

  const handleToggle = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }, [])

  const handleSelect = useCallback(
    (path: string) => {
      setSelectedPath(path)
      onSelect?.(path)
    },
    [onSelect]
  )

  if (!nodes || nodes.length === 0) return null

  return (
    <div
      role="tree"
      className={cn(
        "rounded-lg border border-border bg-background/50 p-2 font-mono text-sm",
        className
      )}
    >
      {nodes.map((node) => (
        <FileTreeNode
          key={node.path}
          node={node}
          depth={0}
          expandedPaths={expandedPaths}
          selectedPath={selectedPath}
          onToggle={handleToggle}
          onSelect={handleSelect}
        />
      ))}
    </div>
  )
}
