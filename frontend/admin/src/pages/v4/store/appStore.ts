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
import type { V4Graph, V4GraphEdge, V4GraphNode } from '../../../api/v4'

// v4 支持的 7 种内置节点（后续扩展 retrieval / human_task / subgraph）
export type V4NodeType = 'start' | 'llm' | 'end' | 'branch' | 'tool' | 'template' | 'http'

export interface V4InputVariable {
  name: string
  type: 'string' | 'number' | 'boolean' | 'json'
  required: boolean
  default: string
}

export interface V4OutputVariable {
  name: string
  value: string
}

export interface V4NodeData extends Record<string, unknown> {
  nodeType: V4NodeType
  label: string
  config: Record<string, unknown>
  debugStatus?: 'running' | 'success' | 'error'
}

export interface V4AppState {
  nodes: Node<V4NodeData>[]
  edges: Edge[]
  selectedNodeId: string | null
  nextIdCounter: Record<V4NodeType, number>

  onNodesChange: (changes: NodeChange<Node<V4NodeData>>[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (connection: Connection) => string | null
  selectNode: (id: string | null) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  addNodeOfType: (type: V4NodeType, position?: { x: number; y: number }) => string | null
  removeNode: (id: string) => void
  loadFromGraph: (graph: V4Graph) => void
  serializeToGraph: () => V4Graph
  reset: () => void
}

const NODE_TYPES: V4NodeType[] = ['start', 'llm', 'end', 'branch', 'tool', 'template', 'http']

function defaultConfigFor(type: V4NodeType): Record<string, unknown> {
  switch (type) {
    case 'start':
      return { inputs: [] as V4InputVariable[] }
    case 'llm':
      return { model_id: '', system_prompt: '', temperature: 0.7, max_tokens: 1024 }
    case 'end':
      return { outputs: [] as V4OutputVariable[] }
    case 'branch':
      return { conditions: [{ field: '', operator: 'eq', value: '' }], routes: { true: '', false: '' } }
    case 'tool':
      return { resource_id: '', params: {} }
    case 'template':
      return { template: '' }
    case 'http':
      return { url: '', method: 'GET', headers: {}, body: '' }
  }
}

/** 根据 edges 找到某个节点的所有直接上游节点 ID 列表 */
export function getUpstreamNodeIds(edges: Edge[], nodeId: string): string[] {
  return edges.filter((e) => e.target === nodeId).map((e) => e.source)
}

/** 根据节点类型列出它会暴露的输出字段名（用于 {{#nodeId.field#}} 提示） */
export function listOutputFields(nodeType: V4NodeType): string[] {
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
  }
}

function labelFor(type: V4NodeType): string {
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
  }
}

function nextPosition(nodes: Node<V4NodeData>[]): { x: number; y: number } {
  return { x: 80 + nodes.length * 220, y: 80 + (nodes.length % 4) * 90 }
}

function fromBackendNode(node: V4GraphNode): Node<V4NodeData> {
  const type = node.type as V4NodeType
  return {
    id: node.id,
    type: 'v4Node',
    position: node.position ?? { x: 0, y: 0 },
    data: {
      nodeType: type,
      label: labelFor(type),
      config: { ...(node.config ?? {}) },
    },
  }
}

function toBackendNode(node: Node<V4NodeData>): V4GraphNode {
  return {
    id: node.id,
    type: node.data.nodeType,
    position: node.position,
    config: { ...node.data.config },
  }
}

function initialCounter(): Record<V4NodeType, number> {
  return { start: 1, llm: 1, end: 1, branch: 1, tool: 1, template: 1, http: 1 }
}

function bumpCounter(
  counter: Record<V4NodeType, number>,
  nodes: Node<V4NodeData>[],
): Record<V4NodeType, number> {
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

export const useV4AppStore = create<V4AppState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  nextIdCounter: initialCounter(),

  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes) })
  },
  onEdgesChange: (changes) => {
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
    const counter = get().nextIdCounter
    const id = `${type}_${counter[type]}`
    const newNode: Node<V4NodeData> = {
      id,
      type: 'v4Node',
      position: position ?? nextPosition(get().nodes),
      data: {
        nodeType: type,
        label: labelFor(type),
        config: defaultConfigFor(type),
      },
    }
    set({
      nodes: [...get().nodes, newNode],
      nextIdCounter: { ...counter, [type]: counter[type] + 1 },
      selectedNodeId: id,
    })
    return null
  },
  removeNode: (id) => {
    set({
      nodes: get().nodes.filter((node) => node.id !== id),
      edges: get().edges.filter((edge) => edge.source !== id && edge.target !== id),
      selectedNodeId: get().selectedNodeId === id ? null : get().selectedNodeId,
    })
  },
  loadFromGraph: (graph) => {
    const nodes = (graph.nodes ?? []).map(fromBackendNode)
    const edges: Edge[] = (graph.edges ?? []).map((edge: V4GraphEdge, index) => ({
      id: `e_${edge.from}_${edge.to}_${index}`,
      source: edge.from,
      target: edge.to,
    }))
    set({
      nodes,
      edges,
      nextIdCounter: bumpCounter(initialCounter(), nodes),
      selectedNodeId: null,
    })
  },
  serializeToGraph: () => {
    const state = get()
    return {
      nodes: state.nodes.map(toBackendNode),
      edges: state.edges.map((edge) => ({ from: edge.source, to: edge.target })),
    }
  },
  reset: () =>
    set({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      nextIdCounter: initialCounter(),
    }),
}))
