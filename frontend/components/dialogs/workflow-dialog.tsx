"use client"

import { useState, useCallback, useRef, useEffect } from "react"
import { Dialog as DialogPrimitive } from "radix-ui"
import { motion, AnimatePresence } from "motion/react"
import {
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
import {
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  Background,
  Controls,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Connection,
  type Node,
  type Edge,
  Handle,
  Position,
  MarkerType,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { useSession } from "next-auth/react"
import { apiClient } from "@/lib/api-client"
import { cn } from "@/lib/utils"
import {
  Loader2,
  Plus,
  Trash2,
  Bot,
  Play,
  Flag,
  Maximize2,
  Minimize2,
  GitBranch,
  LayoutTemplate,
  ChevronDown,
} from "lucide-react"
import type { Agent, Workflow, WorkflowStep } from "@/types/playground"

// ---------------------------------------------------------------------------
// Node type definitions
// ---------------------------------------------------------------------------

type NodeType = "start" | "agent" | "end" | "condition"

interface NodeData {
  node_type: NodeType
  agent_id: string
  agent_name: string
  task: string
  branches?: string[]
  agents: Agent[]
  onUpdate: (id: string, field: string, value: string) => void
  onDelete: (id: string) => void
  onBranchUpdate?: (id: string, branches: string[]) => void
}

// ---------------------------------------------------------------------------
// Visual metadata — single source of truth for colors/icons per node type
// ---------------------------------------------------------------------------

const NODE_META = {
  start: {
    label: "Start",
    Icon: Play,
    handle: "#10b981",
    borderColor: "border-l-emerald-500",
    bg: "bg-emerald-500/5",
    iconColor: "#10b981",
    headerText: "text-emerald-400",
    glow: "hover:shadow-emerald-500/20",
  },
  agent: {
    label: "Agent",
    Icon: Bot,
    handle: "#6366f1",
    borderColor: "border-l-indigo-500",
    bg: "bg-indigo-500/5",
    iconColor: "#6366f1",
    headerText: "text-indigo-400",
    glow: "hover:shadow-indigo-500/20",
  },
  end: {
    label: "End",
    Icon: Flag,
    handle: "#f43f5e",
    borderColor: "border-l-rose-500",
    bg: "bg-rose-500/5",
    iconColor: "#f43f5e",
    headerText: "text-rose-400",
    glow: "hover:shadow-rose-500/20",
  },
  condition: {
    label: "Condition",
    Icon: GitBranch,
    handle: "#f59e0b",
    borderColor: "border-l-amber-500",
    bg: "bg-amber-500/5",
    iconColor: "#f59e0b",
    headerText: "text-amber-400",
    glow: "hover:shadow-amber-500/20",
  },
} as const

// ---------------------------------------------------------------------------
// NodeShell — shared card wrapper for all node types
// ---------------------------------------------------------------------------

function NodeShell({
  id,
  nodeType,
  subtitle,
  children,
  onDelete,
  hasTarget = true,
  hasSource = true,
}: {
  id: string
  nodeType: keyof typeof NODE_META
  subtitle?: string
  children: React.ReactNode
  onDelete: (id: string) => void
  hasTarget?: boolean
  hasSource?: boolean
}) {
  const meta = NODE_META[nodeType]
  const { Icon } = meta

  return (
    <div
      className={cn(
        "w-72 rounded-xl border border-border border-l-[3px] shadow-lg transition-all duration-200",
        "bg-background",
        meta.borderColor,
        meta.bg,
        meta.glow,
        "hover:shadow-xl"
      )}
      style={{ position: "relative" }}
    >
      {hasTarget && (
        <Handle
          type="target"
          position={Position.Top}
          style={{
            width: 14,
            height: 14,
            background: meta.handle,
            border: "2.5px solid rgba(0,0,0,0.35)",
            top: -7,
          }}
        />
      )}

      {/* Header */}
      <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between gap-3 cursor-grab active:cursor-grabbing">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className="flex items-center justify-center w-6 h-6 rounded-md shrink-0"
            style={{ background: `${meta.iconColor}18` }}
          >
            <Icon className="h-3.5 w-3.5" style={{ color: meta.iconColor }} />
          </div>
          <span className={cn("font-semibold text-sm", meta.headerText)}>
            {meta.label}
          </span>
          {subtitle && (
            <span className="text-xs text-muted-foreground truncate max-w-28">
              · {subtitle}
            </span>
          )}
        </div>
        <button
          onClick={() => onDelete(id)}
          className="text-muted-foreground/40 hover:text-destructive shrink-0 nodrag transition-colors p-0.5 rounded"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Body */}
      <div className="p-4 space-y-4 nodrag nopan">
        {children}
      </div>

      {hasSource && (
        <Handle
          type="source"
          position={Position.Bottom}
          style={{
            width: 14,
            height: 14,
            background: meta.handle,
            border: "2.5px solid rgba(0,0,0,0.35)",
            bottom: -7,
          }}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Field wrapper — consistent label + input spacing
// ---------------------------------------------------------------------------

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
        {label}
      </label>
      {children}
      {hint && (
        <p className="text-[10px] text-muted-foreground/55 leading-relaxed">{hint}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// StartNode
// ---------------------------------------------------------------------------

function StartNode({ id, data }: { id: string; data: NodeData }) {
  return (
    <NodeShell id={id} nodeType="start" onDelete={data.onDelete} hasTarget={false}>
      <Field label="Initial Input" hint="If blank, the run dialog's input text is used.">
        <Input
          value={data.task}
          onChange={(e) => data.onUpdate(id, "task", e.target.value)}
          placeholder="Default input (or leave for run time)..."
          className="h-9 text-sm bg-background/70"
        />
      </Field>
    </NodeShell>
  )
}

// ---------------------------------------------------------------------------
// AgentNode
// ---------------------------------------------------------------------------

function AgentNode({ id, data }: { id: string; data: NodeData }) {
  return (
    <NodeShell
      id={id}
      nodeType="agent"
      subtitle={data.agent_name || undefined}
      onDelete={data.onDelete}
    >
      <Field label="Agent">
        <Select
          value={data.agent_id}
          onValueChange={(v) => data.onUpdate(id, "agent_id", v)}
        >
          <SelectTrigger className="h-9 text-sm bg-background/70">
            <SelectValue placeholder="Select agent..." />
          </SelectTrigger>
          <SelectContent>
            {data.agents.map((a) => (
              <SelectItem key={a.id} value={a.id} className="text-sm">
                {a.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Field
        label="Task"
        hint={`Use {{node_id.output}} to pass upstream results into this task.`}
      >
        <Input
          value={data.task}
          onChange={(e) => data.onUpdate(id, "task", e.target.value)}
          placeholder="Describe what this agent should do..."
          className="h-9 text-sm bg-background/70"
        />
      </Field>
    </NodeShell>
  )
}

// ---------------------------------------------------------------------------
// EndNode
// ---------------------------------------------------------------------------

function EndNode({ id, data }: { id: string; data: NodeData }) {
  return (
    <NodeShell id={id} nodeType="end" onDelete={data.onDelete} hasSource={false}>
      <Field label="Label (optional)" hint="Marks a terminal output point of the workflow.">
        <Input
          value={data.task}
          onChange={(e) => data.onUpdate(id, "task", e.target.value)}
          placeholder="e.g. success, failure..."
          className="h-9 text-sm bg-background/70"
        />
      </Field>
    </NodeShell>
  )
}

// ---------------------------------------------------------------------------
// ConditionNode — LLM-based router with named branches
// ---------------------------------------------------------------------------

function ConditionNode({ id, data }: { id: string; data: NodeData }) {
  const branches = data.branches ?? ["branch_a", "branch_b"]
  const meta = NODE_META.condition

  const updateBranch = (idx: number, val: string) => {
    const next = branches.map((b, i) => (i === idx ? val : b))
    data.onBranchUpdate?.(id, next)
  }

  const addBranch = () => {
    if (branches.length >= 6) return
    data.onBranchUpdate?.(id, [...branches, `branch_${String.fromCharCode(97 + branches.length)}`])
  }

  const removeBranch = (idx: number) => {
    if (branches.length <= 2) return
    data.onBranchUpdate?.(id, branches.filter((_, i) => i !== idx))
  }

  return (
    <div
      className={cn(
        "w-80 rounded-xl border border-border border-l-[3px] shadow-lg transition-all duration-200",
        "bg-background",
        meta.borderColor,
        meta.bg,
        meta.glow,
        "hover:shadow-xl"
      )}
      style={{ position: "relative" }}
    >
      {/* Target handle — top center */}
      <Handle
        type="target"
        position={Position.Top}
        style={{ width: 14, height: 14, background: meta.handle, border: "2.5px solid rgba(0,0,0,0.35)", top: -7 }}
      />

      {/* Header */}
      <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between gap-3 cursor-grab active:cursor-grabbing">
        <div className="flex items-center gap-2 min-w-0">
          <div className="flex items-center justify-center w-6 h-6 rounded-md shrink-0" style={{ background: `${meta.iconColor}18` }}>
            <GitBranch className="h-3.5 w-3.5" style={{ color: meta.iconColor }} />
          </div>
          <span className={cn("font-semibold text-sm", meta.headerText)}>Condition</span>
        </div>
        <button
          onClick={() => data.onDelete(id)}
          className="text-muted-foreground/40 hover:text-destructive shrink-0 nodrag transition-colors p-0.5 rounded"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Body */}
      <div className="p-4 space-y-4 nodrag nopan">
        <Field label="Routing Prompt" hint="Describe how to choose a branch. Leave blank to auto-route based on content.">
          <Input
            value={data.task}
            onChange={(e) => data.onUpdate(id, "task", e.target.value)}
            placeholder="e.g. Route based on sentiment..."
            className="h-9 text-sm bg-background/70"
          />
        </Field>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
              Branches
            </label>
            <button
              onClick={addBranch}
              disabled={branches.length >= 6}
              className="text-[10px] text-amber-400 hover:text-amber-300 disabled:opacity-40 flex items-center gap-0.5 nodrag"
            >
              <Plus className="h-3 w-3" /> Add
            </button>
          </div>
          <div className="space-y-1.5">
            {branches.map((b, idx) => (
              <div key={idx} className="flex items-center gap-1.5">
                <Input
                  value={b}
                  onChange={(e) => updateBranch(idx, e.target.value)}
                  placeholder={`branch_${String.fromCharCode(97 + idx)}`}
                  className="h-8 text-xs bg-background/70 font-mono flex-1"
                />
                <button
                  onClick={() => removeBranch(idx)}
                  disabled={branches.length <= 2}
                  className="text-muted-foreground/40 hover:text-destructive disabled:opacity-30 nodrag shrink-0"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
          <p className="text-[10px] text-muted-foreground/55 leading-relaxed">
            Connect each branch handle below to downstream nodes. Downstream nodes inherit the branch name.
          </p>
        </div>
      </div>

      {/* Source handles — one per branch, spread across the bottom with labels */}
      <div className="relative h-8 w-full nodrag nopan px-2">
        {branches.map((b, idx) => {
          const pct = branches.length === 1 ? 50 : (idx / (branches.length - 1)) * 80 + 10
          return (
            <div
              key={b || idx}
              className="absolute flex flex-col items-center"
              style={{ left: `${pct}%`, transform: "translateX(-50%)", top: 0 }}
            >
              <span className="text-[9px] font-mono font-semibold text-amber-400 truncate max-w-16 text-center leading-tight mb-0.5">
                {b || `branch_${idx}`}
              </span>
              <Handle
                id={b || `branch_${idx}`}
                type="source"
                position={Position.Bottom}
                style={{
                  position: "relative",
                  transform: "none",
                  left: "auto",
                  bottom: "auto",
                  top: "auto",
                  width: 12,
                  height: 12,
                  background: meta.handle,
                  border: "2.5px solid rgba(0,0,0,0.35)",
                }}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// nodeTypes — registered outside component to avoid re-registration on re-render
// ---------------------------------------------------------------------------

const nodeTypes = {
  startNode: StartNode,
  workflowNode: AgentNode,  // keep "workflowNode" key for backward compat with saved workflows
  endNode: EndNode,
  conditionNode: ConditionNode,
}

// ---------------------------------------------------------------------------
// Workflow templates — preset node + edge layouts
// ---------------------------------------------------------------------------

interface TemplateNode { id: string; type: string; position: { x: number; y: number }; data: { node_type: NodeType; agent_id: string; task: string; branches?: string[] } }
interface TemplateEdge { source: string; target: string; sourceHandle?: string }
interface WorkflowTemplate { name: string; description: string; nodes: TemplateNode[]; edges: TemplateEdge[] }

// Layout constants — keep nodes from overlapping
// Agent/Start/End nodes: ~288px wide, ~180-240px tall
// Condition node: ~320px wide, ~280-340px tall (taller due to branches)
const NW = 300  // node width + horizontal gap
const NH = 260  // node height + vertical gap

const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    name: "Linear Pipeline",
    description: "Start → Agent → Agent → End",
    nodes: [
      { id: "t-start",  type: "startNode",    position: { x: 160, y: 40        }, data: { node_type: "start", agent_id: "", task: "" } },
      { id: "t-agent1", type: "workflowNode", position: { x: 160, y: 40 + NH   }, data: { node_type: "agent", agent_id: "", task: "First step: analyse the input" } },
      { id: "t-agent2", type: "workflowNode", position: { x: 160, y: 40 + NH*2 }, data: { node_type: "agent", agent_id: "", task: "Second step: refine the output from the previous agent" } },
      { id: "t-end",    type: "endNode",      position: { x: 160, y: 40 + NH*3 }, data: { node_type: "end", agent_id: "", task: "" } },
    ],
    edges: [
      { source: "t-start",  target: "t-agent1" },
      { source: "t-agent1", target: "t-agent2" },
      { source: "t-agent2", target: "t-end" },
    ],
  },
  {
    name: "Parallel Agents",
    description: "Start → two Agents in parallel → End",
    nodes: [
      { id: "t-start",  type: "startNode",    position: { x: NW,     y: 40       }, data: { node_type: "start", agent_id: "", task: "" } },
      { id: "t-agent1", type: "workflowNode", position: { x: 0,      y: 40 + NH  }, data: { node_type: "agent", agent_id: "", task: "Branch A: process the input from one angle" } },
      { id: "t-agent2", type: "workflowNode", position: { x: NW * 2, y: 40 + NH  }, data: { node_type: "agent", agent_id: "", task: "Branch B: process the input from another angle" } },
      { id: "t-end",    type: "endNode",      position: { x: NW,     y: 40 + NH*2}, data: { node_type: "end", agent_id: "", task: "" } },
    ],
    edges: [
      { source: "t-start",  target: "t-agent1" },
      { source: "t-start",  target: "t-agent2" },
      { source: "t-agent1", target: "t-end" },
      { source: "t-agent2", target: "t-end" },
    ],
  },
  {
    name: "Conditional Routing",
    description: "Start → Condition → two Agent branches → End",
    nodes: [
      { id: "t-start",  type: "startNode",    position: { x: NW,     y: 40         }, data: { node_type: "start", agent_id: "", task: "" } },
      { id: "t-cond",   type: "conditionNode",position: { x: NW - 20,y: 40 + NH    }, data: { node_type: "condition", agent_id: "", task: "Route based on the topic or sentiment of the input", branches: ["positive", "negative"] } },
      { id: "t-agent1", type: "workflowNode", position: { x: 0,      y: 40 + NH*2 + 60 }, data: { node_type: "agent", agent_id: "", task: "Handle positive case" } },
      { id: "t-agent2", type: "workflowNode", position: { x: NW * 2, y: 40 + NH*2 + 60 }, data: { node_type: "agent", agent_id: "", task: "Handle negative case" } },
      { id: "t-end",    type: "endNode",      position: { x: NW,     y: 40 + NH*3 + 60 }, data: { node_type: "end", agent_id: "", task: "" } },
    ],
    edges: [
      { source: "t-start",  target: "t-cond" },
      { source: "t-cond",   target: "t-agent1", sourceHandle: "positive" },
      { source: "t-cond",   target: "t-agent2", sourceHandle: "negative" },
      { source: "t-agent1", target: "t-end" },
      { source: "t-agent2", target: "t-end" },
    ],
  },
]

// ---------------------------------------------------------------------------
// NodePalette — toolbar for adding node types
// ---------------------------------------------------------------------------

function NodePalette({
  onAdd,
  hasStartNode,
}: {
  onAdd: (type: NodeType) => void
  hasStartNode: boolean
}) {
  const palette: { type: NodeType; label: string; cls: string; disabled?: boolean }[] = [
    {
      type: "start",
      label: "Start",
      cls: "text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/10",
      disabled: hasStartNode,
    },
    {
      type: "agent",
      label: "Agent",
      cls: "text-indigo-400 border-indigo-500/40 hover:bg-indigo-500/10",
    },
    {
      type: "condition",
      label: "Condition",
      cls: "text-amber-400 border-amber-500/40 hover:bg-amber-500/10",
    },
    {
      type: "end",
      label: "End",
      cls: "text-rose-400 border-rose-500/40 hover:bg-rose-500/10",
    },
  ]

  return (
    <div className="flex items-center gap-2">
      {palette.map(({ type, label, cls, disabled }) => (
        <Button
          key={type}
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => onAdd(type)}
          className={cn("h-8 text-xs gap-1.5 border font-medium px-3.5 disabled:opacity-40", cls)}
        >
          <Plus className="h-3.5 w-3.5" />
          {label}
        </Button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// WorkflowDialog
// ---------------------------------------------------------------------------

interface WorkflowDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agents: Agent[]
  workflow?: Workflow | null  // if provided, dialog is in edit mode
  onCreated?: () => void
  onUpdated?: () => void
}

let _nodeCounter = 1

// Exported wrapper — ReactFlowProvider must wrap the inner component so useReactFlow() works
export function WorkflowDialog(props: WorkflowDialogProps) {
  return (
    <ReactFlowProvider>
      <WorkflowDialogInner {...props} />
    </ReactFlowProvider>
  )
}

function WorkflowDialogInner({ open, onOpenChange, agents, workflow, onCreated, onUpdated }: WorkflowDialogProps) {
  const isEditMode = !!workflow
  const { data: session } = useSession()
  const { screenToFlowPosition, getViewport } = useReactFlow()

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [fullscreen, setFullscreen] = useState(false)
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false)

  // Per-node data store — kept in sync with React Flow node state
  const nodeDataRef = useRef<Record<string, { node_type: NodeType; agent_id: string; task: string; branches?: string[] }>>({})

  const makeNode = useCallback((nodeType: NodeType, x = 100, y = 100): Node => {
    const id = `node-${Date.now()}-${_nodeCounter++}`
    const initialData: { node_type: NodeType; agent_id: string; task: string; branches?: string[] } = { node_type: nodeType, agent_id: "", task: "" }
    if (nodeType === "condition") initialData.branches = ["branch_a", "branch_b"]
    nodeDataRef.current[id] = initialData
    const rfType = nodeType === "start" ? "startNode" : nodeType === "end" ? "endNode" : nodeType === "condition" ? "conditionNode" : "workflowNode"
    return {
      id,
      type: rfType,
      position: { x, y },
      data: {},
    }
  }, [])

  // Always start empty — the useEffect on [open] populates nodes for both create and edit mode.
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  const handleNodeUpdate = useCallback(
    (nodeId: string, field: string, value: string) => {
      nodeDataRef.current[nodeId] = {
        ...(nodeDataRef.current[nodeId] || { node_type: "agent", agent_id: "", task: "" }),
        [field]: value,
      }
      setNodes((nds: Node[]) =>
        nds.map((n: Node) => {
          if (n.id !== nodeId) return n
          const agent =
            field === "agent_id"
              ? agents.find((a) => a.id === value)
              : agents.find((a) => a.id === nodeDataRef.current[nodeId]?.agent_id)
          return {
            ...n,
            data: {
              ...n.data,
              [field]: value,
              agent_name: field === "agent_id" ? (agent?.name ?? "") : n.data.agent_name,
            },
          }
        })
      )
    },
    [agents, setNodes]
  )

  const handleNodeDelete = useCallback(
    (nodeId: string) => {
      delete nodeDataRef.current[nodeId]
      setNodes((nds: Node[]) => nds.filter((n: Node) => n.id !== nodeId))
      setEdges((eds: Edge[]) => eds.filter((e: Edge) => e.source !== nodeId && e.target !== nodeId))
    },
    [setNodes, setEdges]
  )

  const handleBranchUpdate = useCallback(
    (nodeId: string, branches: string[]) => {
      nodeDataRef.current[nodeId] = {
        ...(nodeDataRef.current[nodeId] || { node_type: "condition", agent_id: "", task: "" }),
        branches,
      }
      setNodes((nds: Node[]) =>
        nds.map((n: Node) => (n.id === nodeId ? { ...n, data: { ...n.data, branches } } : n))
      )
    },
    [setNodes]
  )

  const onConnect = useCallback(
    (connection: Connection) => {
      // Check if source node is a condition node → use amber edge color
      const srcNode = nodes.find((n) => n.id === connection.source)
      const isCondition = srcNode?.type === "conditionNode"
      const edgeColor = isCondition ? "#f59e0b" : "#6b7280"
      const edgeData: Partial<Edge> & Connection = {
        ...connection,
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor },
        style: { stroke: edgeColor, strokeWidth: 2 },
      }
      if (isCondition && connection.sourceHandle) {
        edgeData.label = connection.sourceHandle
        edgeData.labelStyle = { fontSize: 10, fill: "#f59e0b", fontWeight: 600 }
        edgeData.labelBgStyle = { fill: "transparent" }
      }
      setEdges((eds: Edge[]) => addEdge(edgeData, eds))
    },
    [setEdges, nodes]
  )

  const addNode = (type: NodeType) => {
    // Place the new node at the center of the current viewport
    const vp = getViewport()
    // Get the canvas element dimensions (approximate — use a sensible default)
    const canvasW = 860
    const canvasH = 480
    // Convert screen center to flow coordinates
    const centerX = (canvasW / 2 - vp.x) / vp.zoom
    const centerY = (canvasH / 2 - vp.y) / vp.zoom
    // Offset slightly so repeated adds don't land on the same spot
    const offset = nodes.length * 20
    setNodes((nds: Node[]) => [...nds, makeNode(type, centerX - 144 + offset, centerY - 80 + offset)])
  }

  // Track previous open state so we only initialise on the false→true transition.
  const prevOpenRef = useRef(false)

  const resetForm = useCallback(() => {
    setName("")
    setDescription("")
    setError("")
    setFullscreen(false)
    nodeDataRef.current = {}
    _nodeCounter = 1
    setNodes([makeNode("start", 200, 60)])
    setEdges([])
    prevOpenRef.current = false  // allow next open to re-initialise
  }, [makeNode, setNodes, setEdges])
  useEffect(() => {
    const wasOpen = prevOpenRef.current
    prevOpenRef.current = open
    if (!open || wasOpen) return

    setError("")
    setFullscreen(false)
    nodeDataRef.current = {}

    if (!workflow) {
      // Create mode — reset to a single Start node
      setName("")
      setDescription("")
      _nodeCounter = 1
      setNodes([makeNode("start", 200, 60)])
      setEdges([])
      return
    }

    // Edit mode — reconstruct canvas from saved workflow steps
    setName(workflow.name)
    setDescription(workflow.description || "")

    const sortedSteps = [...workflow.steps].sort((a, b) => a.order - b.order)

    const newNodes: Node[] = sortedSteps.map((step) => {
      const id = step.id || `node-${Date.now()}-${_nodeCounter++}`
      const nodeType = (step.node_type as NodeType) || "agent"
      const rfType = nodeType === "start" ? "startNode" : nodeType === "end" ? "endNode" : nodeType === "condition" ? "conditionNode" : "workflowNode"
      const data: { node_type: NodeType; agent_id: string; task: string; branches?: string[] } = {
        node_type: nodeType,
        agent_id: step.agent_id || "",
        task: step.task || "",
      }
      if (nodeType === "condition" && step.config?.branches) {
        data.branches = step.config.branches as string[]
      }
      nodeDataRef.current[id] = data
      return { id, type: rfType, position: step.position || { x: 160, y: (step.order - 1) * 260 + 40 }, data: {} }
    })

    const newEdges: Edge[] = []
    sortedSteps.forEach((step) => {
      const targetId = newNodes.find((n, i) => sortedSteps[i]?.id === step.id || sortedSteps[i] === step)?.id
      if (!targetId) return
      ;(step.depends_on || []).forEach((depId) => {
        const sourceId = newNodes.find((n, i) => sortedSteps[i]?.id === depId || newNodes[i]?.id === depId)?.id || depId
        const srcNodeType = nodeDataRef.current[sourceId]?.node_type
        const isCondition = srcNodeType === "condition"
        const edgeColor = isCondition ? "#f59e0b" : "#6b7280"
        const edgeId = `e-${sourceId}-${targetId}${step.input_branch ? `-${step.input_branch}` : ""}`
        newEdges.push({
          id: edgeId,
          source: sourceId,
          target: targetId,
          sourceHandle: step.input_branch || undefined,
          type: "smoothstep",
          style: { stroke: edgeColor, strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: edgeColor },
          label: step.input_branch || undefined,
          labelStyle: step.input_branch ? { fontSize: 10, fill: "#f59e0b", fontWeight: 600 } : undefined,
          labelBgStyle: step.input_branch ? { fill: "transparent" } : undefined,
        })
      })
    })

    setNodes(newNodes)
    setEdges(newEdges)
  }, [open, workflow, makeNode, setNodes, setEdges])

  const loadTemplate = (tpl: WorkflowTemplate) => {
    // Rebuild nodeDataRef and nodes from template
    nodeDataRef.current = {}
    const newNodes: Node[] = tpl.nodes.map((tn) => {
      nodeDataRef.current[tn.id] = { ...tn.data }
      return { id: tn.id, type: tn.type, position: tn.position, data: {} }
    })
    const newEdges: Edge[] = tpl.edges.map((te, i) => ({
      id: `te-${i}`,
      source: te.source,
      target: te.target,
      sourceHandle: te.sourceHandle,
      type: "smoothstep",
      style: { stroke: te.sourceHandle ? "#f59e0b" : "#6b7280", strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: te.sourceHandle ? "#f59e0b" : "#6b7280" },
      label: te.sourceHandle ?? undefined,
      labelStyle: te.sourceHandle ? { fontSize: 10, fill: "#f59e0b", fontWeight: 600 } : undefined,
      labelBgStyle: te.sourceHandle ? { fill: "transparent" } : undefined,
    }))
    setNodes(newNodes)
    setEdges(newEdges)
    if (!name) setName(tpl.name)
    if (!description) setDescription(tpl.description)
  }

  const handleCreate = async () => {
    if (!session?.accessToken || !name) return

    // Nodes valid by type: agent must have agent_id + task; start/end always valid
    const validNodes = nodes.filter((n) => {
      const d = nodeDataRef.current[n.id]
      if (!d) return false
      if (d.node_type === "agent") return !!(d.agent_id && d.task)
      return true
    })

    const hasAgentNode = validNodes.some((n) => nodeDataRef.current[n.id]?.node_type === "agent")
    if (!hasAgentNode) {
      setError("Add at least one Agent node with an agent and task selected.")
      return
    }

    // Build depends_on and input_branch from edges
    // source → target means target depends on source
    // For condition edges, sourceHandle encodes the branch label
    const dependsOnMap: Record<string, string[]> = {}
    const inputBranchMap: Record<string, string> = {}  // node_id → branch label
    for (const edge of edges) {
      if (!dependsOnMap[edge.target]) dependsOnMap[edge.target] = []
      dependsOnMap[edge.target].push(edge.source)
      // If the edge's source is a condition node and has a sourceHandle, record the branch
      const srcData = nodeDataRef.current[edge.source]
      if (srcData?.node_type === "condition" && edge.sourceHandle) {
        inputBranchMap[edge.target] = edge.sourceHandle
      }
    }

    const steps: WorkflowStep[] = validNodes.map((n, i) => {
      const d = nodeDataRef.current[n.id]
      const step: WorkflowStep = {
        id: n.id,
        node_type: d.node_type,
        agent_id: d.node_type === "agent" ? d.agent_id : undefined,
        task: d.task,
        order: i + 1,
        depends_on: dependsOnMap[n.id] ?? [],
        position: n.position,
      }
      if (inputBranchMap[n.id]) {
        step.input_branch = inputBranchMap[n.id]
      }
      if (d.node_type === "condition") {
        step.config = {
          branches: d.branches ?? ["branch_a", "branch_b"],
          condition_prompt: d.task,
        }
      }
      return step
    })

    setLoading(true)
    setError("")
    try {
      if (isEditMode && workflow) {
        await apiClient.updateWorkflow(workflow.id, { name, description: description || undefined, steps })
        resetForm()
        onOpenChange(false)
        onUpdated?.()
      } else {
        await apiClient.createWorkflow({ name, description: description || undefined, steps })
        resetForm()
        onOpenChange(false)
        onCreated?.()
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : isEditMode ? "Failed to update workflow" : "Failed to create workflow"
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const hasStartNode = nodes.some((n) => n.type === "startNode")

  const handleOpenChange = (v: boolean) => { if (!v) resetForm(); onOpenChange(v) }

  return (
    <DialogPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      {/* forceMount keeps the portal — and ReactFlow canvas — always mounted.
          We animate the overlay + content manually so the canvas never unmounts/remounts. */}
      <DialogPrimitive.Portal forceMount>
        <AnimatePresence>
          {open && (
            <>
              <DialogPrimitive.Overlay asChild forceMount>
                <motion.div
                  key="wf-overlay"
                  className="fixed inset-0 z-50 bg-black/50"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2, ease: "easeInOut" }}
                />
              </DialogPrimitive.Overlay>
              <DialogPrimitive.Content asChild forceMount>
                <motion.div
                  key="wf-content"
                  className={cn(
                    "bg-background fixed top-1/2 left-1/2 z-50 flex flex-col border rounded-lg shadow-lg outline-none p-6 gap-4",
                    fullscreen
                      ? "w-[98vw] h-[96vh]"
                      : "w-[min(900px,calc(100vw-2rem))] h-[85vh]"
                  )}
                  style={{ translateX: "-50%", translateY: "-50%" }}
                  initial={{ opacity: 0, filter: "blur(4px)", scale: 0.95 }}
                  animate={{ opacity: 1, filter: "blur(0px)", scale: 1 }}
                  exit={{ opacity: 0, filter: "blur(4px)", scale: 0.95 }}
                  transition={{ type: "spring", stiffness: 150, damping: 25 }}
                >
                  <DialogPrimitive.Close className="absolute top-4 right-4 rounded-xs opacity-70 transition-opacity hover:opacity-100 focus:outline-none [&_svg]:size-4">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
                    <span className="sr-only">Close</span>
                  </DialogPrimitive.Close>
        {/* Header — no fullscreen button here to avoid collision with the Dialog X close button */}
        <DialogHeader>
          <DialogTitle>{isEditMode ? "Edit Workflow" : "Create Workflow"}</DialogTitle>
          <DialogDescription>
            Build a DAG pipeline — connect a node&apos;s bottom handle to another&apos;s top handle to create dependencies.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3 flex-1 min-h-0">
          {/* Metadata row */}
          <div className="grid grid-cols-2 gap-3 shrink-0">
            <div className="grid gap-1.5">
              <Label htmlFor="wf-name" className="text-xs font-medium">Name *</Label>
              <Input
                id="wf-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Content Pipeline"
                className="h-9 text-sm"
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="wf-desc" className="text-xs font-medium">Description</Label>
              <Input
                id="wf-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional description..."
                className="h-9 text-sm"
              />
            </div>
          </div>

          {/* Canvas toolbar */}
          <div className="flex items-center justify-between shrink-0">
            <span className="text-xs text-muted-foreground">
              {nodes.length} node{nodes.length !== 1 ? "s" : ""} · {edges.length} edge{edges.length !== 1 ? "s" : ""}
            </span>
            <div className="flex items-center gap-2">
              {/* Template picker */}
              <div className="relative">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs gap-1.5 border font-medium px-3 text-muted-foreground border-border hover:text-foreground"
                  onClick={() => setTemplateMenuOpen((v) => !v)}
                >
                  <LayoutTemplate className="h-3.5 w-3.5" />
                  Templates
                  <ChevronDown className="h-3 w-3 opacity-60" />
                </Button>
                {templateMenuOpen && (
                  <>
                  <div className="fixed inset-0 z-40" onClick={() => setTemplateMenuOpen(false)} />
                  <div className="absolute right-0 top-full mt-1 z-50 w-64 rounded-lg border border-border bg-popover shadow-xl">
                    <p className="px-3 pt-2.5 pb-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                      Load a starting template
                    </p>
                    {WORKFLOW_TEMPLATES.map((tpl) => (
                      <button
                        key={tpl.name}
                        onClick={() => { loadTemplate(tpl); setTemplateMenuOpen(false) }}
                        className="w-full text-left px-3 py-2.5 hover:bg-accent transition-colors"
                      >
                        <div className="text-xs font-medium text-foreground">{tpl.name}</div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">{tpl.description}</div>
                      </button>
                    ))}
                  </div>
                  </>
                )}
              </div>
              <div className="w-px h-5 bg-border" />
              <NodePalette onAdd={addNode} hasStartNode={hasStartNode} />
              <div className="w-px h-5 bg-border" />
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground hover:text-foreground"
                onClick={() => setFullscreen((f) => !f)}
                title={fullscreen ? "Exit fullscreen" : "Expand canvas"}
              >
                {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
              </Button>
            </div>
          </div>

          {/* React Flow canvas */}
          <div
            className="flex-1 min-h-0 rounded-lg border border-border bg-muted/10"
            style={{ position: "relative" }}
          >
            <ReactFlow
              nodes={nodes.map((n) => ({
                ...n,
                data: {
                  ...n.data,
                  ...nodeDataRef.current[n.id],
                  agents,
                  onUpdate: handleNodeUpdate,
                  onDelete: handleNodeDelete,
                  onBranchUpdate: handleBranchUpdate,
                },
              }))}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              nodeTypes={nodeTypes}
              defaultViewport={{ x: 60, y: 40, zoom: 0.75 }}
              minZoom={0.15}
              maxZoom={2}
              snapToGrid
              snapGrid={[20, 20]}
              defaultEdgeOptions={{
                type: "smoothstep",
                style: { stroke: "#6b7280", strokeWidth: 2 },
                markerEnd: { type: MarkerType.ArrowClosed, color: "#6b7280" },
              }}
              proOptions={{ hideAttribution: true }}
              style={{ width: "100%", height: "100%" }}
            >
              <Background gap={20} size={1} color="hsl(var(--border))" />
              <Controls />
            </ReactFlow>
          </div>
        </div>

        {error && <p className="text-xs text-destructive shrink-0 pt-1">{error}</p>}

        <DialogFooter className="shrink-0">
          <Button variant="outline" size="lg" onClick={() => { resetForm(); onOpenChange(false) }}>
            Cancel
          </Button>
          <Button size="lg" onClick={handleCreate} disabled={loading || !name}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
            {isEditMode ? "Save Changes" : "Create Workflow"}
          </Button>
        </DialogFooter>
                </motion.div>
              </DialogPrimitive.Content>
            </>
          )}
        </AnimatePresence>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}
