import type { Edge, Node } from '@xyflow/react'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import { create } from 'zustand'
import type { Graph, GraphEdge, GraphNode } from '../../../api/apps'

// apps 支持的 10 种内置节点 + 1 种画布注释便签
export type NodeType =
  | 'start'
  | 'llm'
  | 'end'
  | 'branch'
  | 'tool'
  | 'template'
  | 'http'
  | 'retrieval'
  | 'human_task'
  | 'subgraph'
  | 'sticky'

export interface InputVariable {
  name: string
  type: 'string' | 'number' | 'boolean' | 'json'
  required: boolean
  default: string
}

export interface OutputVariable {
  name: string
  value: string
}

export interface NodeData extends Record<string, unknown> {
  nodeType: NodeType
  label: string
  config: Record<string, unknown>
  debugStatus?: 'pending' | 'running' | 'success' | 'error'
}

interface Snapshot {
  nodes: Node<NodeData>[]
  edges: Edge[]
  nextIdCounter: Record<NodeType, number>
}

export interface AppState {
  nodes: Node<NodeData>[]
  edges: Edge[]
  selectedNodeId: string | null
  nextIdCounter: Record<NodeType, number>
  clipboardNode: Node<NodeData> | null
  past: Snapshot[]
  future: Snapshot[]
  runStepNodeId: string | null

  onNodesChange: (changes: NodeChange<Node<NodeData>>[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (connection: Connection) => string | null
  selectNode: (id: string | null) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  addNodeOfType: (type: NodeType, position?: { x: number; y: number }) => string | null
  removeNode: (id: string) => void
  duplicateNode: (id: string) => void
  copyNode: (id: string) => void
  pasteNode: () => void
  renameNode: (id: string, label: string) => void
  insertNodeBetween: (source: string, target: string, newType: NodeType) => void
  addNodeAfter: (sourceNodeId: string, newType: NodeType) => string | null
  loadFromGraph: (graph: Graph) => void
  serializeToGraph: () => Graph
  reset: () => void
  undo: () => void
  redo: () => void
  pushHistory: () => void
  triggerRunStep: (nodeId: string) => void
  clearRunStep: () => void
}

const NODE_TYPES: NodeType[] = [
  'start',
  'llm',
  'end',
  'branch',
  'tool',
  'template',
  'http',
  'retrieval',
  'human_task',
  'subgraph',
  'sticky',
]

function defaultConfigFor(type: NodeType): Record<string, unknown> {
  switch (type) {
    case 'start':
      return { inputs: [] as InputVariable[] }
    case 'llm':
      return { model_id: '', system_prompt: '', temperature: 0.7, max_tokens: 1024 }
    case 'end':
      return { outputs: [] as OutputVariable[] }
    case 'branch':
      return { conditions: [{ field: '', operator: 'eq', value: '' }], routes: { true: '', false: '' } }
    case 'tool':
      return { resource_id: '', params: {} }
    case 'template':
      return { template: '' }
    case 'http':
      return { url: '', method: 'GET', headers: {}, body: '' }
    case 'retrieval':
      return { knowledge_base_id: '', query_field: 'query', top_k: 5 }
    case 'human_task':
      return { assignee_role: 'reviewer', instructions: '' }
    case 'subgraph':
      return { application_id: '', input_mapping: {} }
    case 'sticky':
      return { content: '双击编辑注释', color: '#fffbe6' }
  }
}

/** 根据 edges 找到某个节点的所有直接上游节点 ID 列表 */
export function getUpstreamNodeIds(edges: Edge[], nodeId: string): string[] {
  return edges.filter((e) => e.target === nodeId).map((e) => e.source)
}

/** 根据节点类型列出它会暴露的输出字段名（用于 {{#nodeId.field#}} 提示） */
export function listOutputFields(nodeType: NodeType): string[] {
  switch (nodeType) {
    case 'start':
      return ['input']
    case 'llm':
      return ['output', 'usage', 'model']
    case 'end':
      return ['output']
    case 'tool':
      return ['result', 'error']
    case 'template':
      return ['text']
    case 'http':
      return ['status', 'body', 'headers']
    case 'branch':
      return ['true', 'false']
    case 'retrieval':
      return ['results', 'count']
    case 'human_task':
      return ['output']
    case 'subgraph':
      return ['output']
    case 'sticky':
      return []
  }
}

function labelFor(type: NodeType): string {
  switch (type) {
    case 'start':
      return '开始'
    case 'llm':
      return 'LLM'
    case 'end':
      return '结束'
    case 'branch':
      return '条件分支'
    case 'tool':
      return '工具'
    case 'template':
      return '模板'
    case 'http':
      return 'HTTP'
    case 'retrieval':
      return '检索'
    case 'human_task':
      return '人审'
    case 'subgraph':
      return '子图'
    case 'sticky':
      return '注释'
  }
}

function nextPosition(nodes: Node<NodeData>[]): { x: number; y: number } {
  return { x: 80 + nodes.length * 220, y: 80 + (nodes.length % 4) * 90 }
}

function fromBackendNode(node: GraphNode): Node<NodeData> {
  const type = node.type as NodeType
  return {
    id: node.id,
    type: 'appNode',
    position: node.position ?? { x: 0, y: 0 },
    data: {
      nodeType: type,
      label: labelFor(type),
      config: { ...(node.config ?? {}) },
    },
  }
}

function toBackendNode(node: Node<NodeData>): GraphNode {
  return {
    id: node.id,
    type: node.data.nodeType,
    position: node.position,
    config: { ...node.data.config },
  }
}

function initialCounter(): Record<NodeType, number> {
  return {
    start: 1,
    llm: 1,
    end: 1,
    branch: 1,
    tool: 1,
    template: 1,
    http: 1,
    retrieval: 1,
    human_task: 1,
    subgraph: 1,
    sticky: 1,
  }
}

function bumpCounter(
  counter: Record<NodeType, number>,
  nodes: Node<NodeData>[],
): Record<NodeType, number> {
  const next = { ...counter }
  for (const node of nodes) {
    const type = node.data.nodeType
    const match = /^(\w+)_(\d+)$/.exec(node.id)
    if (match && NODE_TYPES.includes(type)) {
      next[type] = Math.max(next[type], Number(match[2]) + 1)
    }
  }
  return next
}

/** 为指定类型分配一个新节点 id，同时推进计数器 */
function allocateNodeId(
  state: AppState,
  type: NodeType,
): { id: string; nextIdCounter: Record<NodeType, number> } {
  const counter = state.nextIdCounter
  const id = `${type}_${counter[type]}`
  return { id, nextIdCounter: { ...counter, [type]: counter[type] + 1 } }
}

function takeSnapshot(state: AppState): Snapshot {
  return {
    nodes: JSON.parse(JSON.stringify(state.nodes)),
    edges: JSON.parse(JSON.stringify(state.edges)),
    nextIdCounter: { ...state.nextIdCounter },
  }
}

const HISTORY_LIMIT = 50

export const useAppStore = create<AppState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  nextIdCounter: initialCounter(),
  clipboardNode: null,
  past: [],
  future: [],
  runStepNodeId: null,

  pushHistory: () => {
    const snap = takeSnapshot(get())
    set({
      past: [...get().past.slice(-(HISTORY_LIMIT - 1)), snap],
      future: [],
    })
  },

  onNodesChange: (changes) => {
    // 拖动结束（dragging false）时快照一次，避免 mousemove 频繁入栈
    const dragEnded = changes.some((c) => c.type === 'position' && c.dragging === false)
    if (dragEnded) get().pushHistory()
    set({ nodes: applyNodeChanges(changes, get().nodes) })
  },
  onEdgesChange: (changes) => {
    if (changes.length > 0) get().pushHistory()
    set({ edges: applyEdgeChanges(changes, get().edges) })
  },
  onConnect: (connection) => {
    const { source, target } = connection
    if (!source || !target) return null
    if (source === target) return '不能连接节点自身'
    const sourceNode = get().nodes.find((n) => n.id === source)
    const targetNode = get().nodes.find((n) => n.id === target)
    if (!sourceNode || !targetNode) return '节点不存在'
    if (sourceNode.data.nodeType === 'end') return '结束节点不能作为连线起点'
    if (targetNode.data.nodeType === 'start') return '开始节点不能作为连线终点'
    const duplicate = get().edges.some(
      (e) => e.source === source && e.target === target,
    )
    if (duplicate) return '两节点间已存在连线'
    get().pushHistory()
    set({
      edges: addEdge(
        { ...connection, id: `e_${source}_${target}_${get().edges.length}` },
        get().edges,
      ),
    })
    return null
  },
  selectNode: (id) => set({ selectedNodeId: id }),
  updateNodeConfig: (id, config) => {
    get().pushHistory()
    set({
      nodes: get().nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, config } } : node,
      ),
    })
  },
  addNodeOfType: (type, position) => {
    if (type === 'start' && get().nodes.some((n) => n.data.nodeType === 'start')) {
      return '画布上只能有一个开始节点'
    }
    if (type === 'end' && get().nodes.some((n) => n.data.nodeType === 'end')) {
      return '画布上只能有一个结束节点'
    }
    get().pushHistory()
    const state = get()
    const { id, nextIdCounter } = allocateNodeId(state, type)
    const newNode: Node<NodeData> = {
      id,
      type: type === 'sticky' ? 'sticky' : 'appNode',
      position: position ?? nextPosition(state.nodes),
      data: {
        nodeType: type,
        label: labelFor(type),
        config: defaultConfigFor(type),
      },
    }
    set({
      nodes: [...state.nodes, newNode],
      nextIdCounter,
      selectedNodeId: id,
    })
    return null
  },
  removeNode: (id) => {
    get().pushHistory()
    set({
      nodes: get().nodes.filter((node) => node.id !== id),
      edges: get().edges.filter((edge) => edge.source !== id && edge.target !== id),
      selectedNodeId: get().selectedNodeId === id ? null : get().selectedNodeId,
    })
  },
  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id)
    if (!src) return
    const type = src.data.nodeType
    if (type === 'start' || type === 'end') return
    get().pushHistory()
    const state = get()
    const { id: newId, nextIdCounter } = allocateNodeId(state, type)
    const copy: Node<NodeData> = {
      ...src,
      id: newId,
      position: { x: src.position.x + 40, y: src.position.y + 60 },
      selected: true,
      data: {
        ...src.data,
        label: `${src.data.label} 副本`,
        config: JSON.parse(JSON.stringify(src.data.config ?? {})),
      },
    }
    set({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), copy],
      nextIdCounter,
      selectedNodeId: newId,
    })
  },
  copyNode: (id) => {
    const src = get().nodes.find((n) => n.id === id)
    if (!src) return
    set({ clipboardNode: JSON.parse(JSON.stringify(src)) })
  },
  pasteNode: () => {
    const clip = get().clipboardNode
    if (!clip) return
    const type = clip.data.nodeType
    if (type === 'start' || type === 'end') return
    get().pushHistory()
    const state = get()
    const { id: newId, nextIdCounter } = allocateNodeId(state, type)
    const copy: Node<NodeData> = {
      ...clip,
      id: newId,
      position: { x: clip.position.x + 40, y: clip.position.y + 60 },
      selected: true,
    }
    set({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), copy],
      nextIdCounter,
      selectedNodeId: newId,
    })
  },
  renameNode: (id, label) => {
    get().pushHistory()
    set({
      nodes: get().nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, label } } : node,
      ),
    })
  },
  insertNodeBetween: (source, target, newType) => {
    const state = get()
    if (newType === 'start' || newType === 'end') return
    const srcNode = state.nodes.find((n) => n.id === source)
    const tgtNode = state.nodes.find((n) => n.id === target)
    if (!srcNode || !tgtNode) return
    get().pushHistory()
    // 计算中点位置
    const x = (srcNode.position.x + tgtNode.position.x) / 2 - 80
    const y = (srcNode.position.y + tgtNode.position.y) / 2 - 30
    const { id: newId, nextIdCounter } = allocateNodeId(state, newType)
    const newNode: Node<NodeData> = {
      id: newId,
      type: 'appNode',
      position: { x, y },
      selected: true,
      data: {
        nodeType: newType,
        label: labelFor(newType),
        config: defaultConfigFor(newType),
      },
    }
    // 移除原 source→target 连线
    const remainingEdges = state.edges.filter(
      (e) => !(e.source === source && e.target === target),
    )
    const newEdges: Edge[] = [
      ...remainingEdges,
      { id: `e_${source}_${newId}_${remainingEdges.length}`, source, target: newId },
      { id: `e_${newId}_${target}_${remainingEdges.length + 1}`, source: newId, target },
    ]
    set({
      nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), newNode],
      edges: newEdges,
      nextIdCounter,
      selectedNodeId: newId,
    })
  },
  addNodeAfter: (sourceNodeId, newType) => {
    if (newType === 'start' || newType === 'end') return '不能在下游添加开始/结束节点'
    const state = get()
    const srcNode = state.nodes.find((n) => n.id === sourceNodeId)
    if (!srcNode) return '源节点不存在'
    get().pushHistory()
    const next = get()
    const { id: newId, nextIdCounter } = allocateNodeId(next, newType)
    const newNode: Node<NodeData> = {
      id: newId,
      type: 'appNode',
      position: { x: srcNode.position.x + 240, y: srcNode.position.y },
      selected: true,
      data: {
        nodeType: newType,
        label: labelFor(newType),
        config: defaultConfigFor(newType),
      },
    }
    const newEdge: Edge = {
      id: `e_${sourceNodeId}_${newId}_${next.edges.length}`,
      source: sourceNodeId,
      target: newId,
    }
    set({
      nodes: [...next.nodes.map((n) => ({ ...n, selected: false })), newNode],
      edges: [...next.edges, newEdge],
      nextIdCounter,
      selectedNodeId: newId,
    })
    return null
  },
  loadFromGraph: (graph) => {
    const nodes = (graph.nodes ?? []).map(fromBackendNode)
    const edges: Edge[] = (graph.edges ?? []).map((edge: GraphEdge, index) => ({
      id: `e_${edge.from}_${edge.to}_${index}`,
      source: edge.from,
      target: edge.to,
    }))
    set({
      nodes,
      edges,
      nextIdCounter: bumpCounter(initialCounter(), nodes),
      selectedNodeId: null,
      past: [],
      future: [],
    })
  },
  serializeToGraph: () => {
    const state = get()
    return {
      nodes: state.nodes.map(toBackendNode),
      edges: state.edges.map((edge) => ({ from: edge.source, to: edge.target })),
    }
  },
  undo: () => {
    const past = get().past
    if (past.length === 0) return
    const prev = past[past.length - 1]
    const current = takeSnapshot(get())
    set({
      nodes: prev.nodes,
      edges: prev.edges,
      nextIdCounter: prev.nextIdCounter,
      past: past.slice(0, -1),
      future: [current, ...get().future].slice(0, HISTORY_LIMIT),
    })
  },
  redo: () => {
    const future = get().future
    if (future.length === 0) return
    const next = future[0]
    const current = takeSnapshot(get())
    set({
      nodes: next.nodes,
      edges: next.edges,
      nextIdCounter: next.nextIdCounter,
      past: [...get().past, current].slice(-HISTORY_LIMIT),
      future: future.slice(1),
    })
  },
  reset: () =>
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      nextIdCounter: initialCounter(),
      clipboardNode: null,
      past: [],
      future: [],
      runStepNodeId: null,
    }),

  triggerRunStep: (nodeId) => set({ runStepNodeId: nodeId }),
  clearRunStep: () => set({ runStepNodeId: null }),
}))
