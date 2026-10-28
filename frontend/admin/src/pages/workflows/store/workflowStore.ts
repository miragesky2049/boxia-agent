import type { Edge, Node } from '@xyflow/react'
import {
  applyEdgeChanges,
  applyNodeChanges,
  addEdge,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import { create } from 'zustand'
import type { WorkflowGraph, WorkflowGraphNode } from '../../../api/workflows'

export type WorkflowNodeType = 'start' | 'llm' | 'tool' | 'end'

export interface WorkflowNodeData extends Record<string, unknown> {
  nodeType: WorkflowNodeType
  label: string
  config: Record<string, unknown>
}

export interface WorkflowState {
  nodes: Node<WorkflowNodeData>[]
  edges: Edge[]
  variables: Array<{ key: string; type: string; required?: boolean; default?: unknown }>
  selectedNodeId: string | null
  nextIdCounter: Record<WorkflowNodeType, number>

  onNodesChange: (changes: NodeChange<Node<WorkflowNodeData>>[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (connection: Connection) => void
  selectNode: (id: string | null) => void
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void
  addNodeOfType: (type: WorkflowNodeType) => void
  loadFromGraph: (graph: WorkflowGraph) => void
  serializeToGraph: () => WorkflowGraph
  reset: () => void
}

function defaultDataFor(type: WorkflowNodeType): Record<string, unknown> {
  switch (type) {
    case 'start':
      return { output_schema: { query: 'string' } }
    case 'llm':
      return {
        model_id: 'default',
        system_prompt_tpl: '',
        user_prompt_tpl: '{{query}}',
        temperature: 0.7,
      }
    case 'tool':
      return { tool_id: '', arguments_tpl: {} }
    case 'end':
      return { output_tpl: { answer: '{{llm_1.output}}' } }
  }
}

function labelFor(type: WorkflowNodeType): string {
  switch (type) {
    case 'start':
      return 'Start'
    case 'llm':
      return 'LLM'
    case 'tool':
      return 'Tool'
    case 'end':
      return 'End'
  }
}

function nextPosition(nodes: Node<WorkflowNodeData>[]): { x: number; y: number } {
  return { x: 80 + nodes.length * 240, y: 80 + (nodes.length % 3) * 80 }
}

function fromBackendNode(node: WorkflowGraphNode): Node<WorkflowNodeData> {
  const type = node.type as WorkflowNodeType
  return {
    id: node.id,
    type: 'workflowNode',
    position: node.position ?? { x: 0, y: 0 },
    data: {
      nodeType: type,
      label: labelFor(type),
      config: { ...(node.data ?? {}) },
    },
  }
}

function toBackendNode(node: Node<WorkflowNodeData>): WorkflowGraphNode {
  return {
    id: node.id,
    type: node.data.nodeType,
    position: node.position,
    data: { ...node.data.config },
  }
}

export const useWorkflowStore = create<WorkflowState>((set, get) => ({
  nodes: [],
  edges: [],
  variables: [],
  selectedNodeId: null,
  nextIdCounter: { start: 1, llm: 1, tool: 1, end: 1 },

  onNodesChange: (changes) => {
    set({ nodes: applyNodeChanges(changes, get().nodes) })
  },
  onEdgesChange: (changes) => {
    set({ edges: applyEdgeChanges(changes, get().edges) })
  },
  onConnect: (connection) => {
    set({ edges: addEdge({ ...connection, id: `e_${connection.source}_${connection.target}` }, get().edges) })
  },
  selectNode: (id) => set({ selectedNodeId: id }),
  updateNodeConfig: (id, config) => {
    set({
      nodes: get().nodes.map((node) =>
        node.id === id ? { ...node, data: { ...node.data, config } } : node,
      ),
    })
  },
  addNodeOfType: (type) => {
    const counter = get().nextIdCounter
    const id = `${type}_${counter[type]}`
    const nextCounter = { ...counter, [type]: counter[type] + 1 }
    const newNode: Node<WorkflowNodeData> = {
      id,
      type: 'workflowNode',
      position: nextPosition(get().nodes),
      data: {
        nodeType: type,
        label: labelFor(type),
        config: defaultDataFor(type),
      },
    }
    set({
      nodes: [...get().nodes, newNode],
      nextIdCounter: nextCounter,
      selectedNodeId: id,
    })
  },
  loadFromGraph: (graph) => {
    const nodes = (graph.nodes ?? []).map(fromBackendNode)
    const edges = (graph.edges ?? []).map((edge, index) => ({
      id: `e_${edge.source}_${edge.target}_${index}`,
      source: edge.source,
      target: edge.target,
    }))
    const counter: Record<WorkflowNodeType, number> = { start: 1, llm: 1, tool: 1, end: 1 }
    for (const node of nodes) {
      const type = node.data.nodeType
      const match = /^(\w+)_(\d+)$/.exec(node.id)
      if (match) {
        counter[type] = Math.max(counter[type], Number(match[2]) + 1)
      }
    }
    set({
      nodes,
      edges,
      variables: graph.variables ?? [],
      nextIdCounter: counter,
      selectedNodeId: null,
    })
  },
  serializeToGraph: () => {
    const state = get()
    return {
      variables: state.variables,
      nodes: state.nodes.map(toBackendNode),
      edges: state.edges.map((edge) => ({ source: edge.source, target: edge.target })),
    }
  },
  reset: () =>
    set({
      nodes: [],
      edges: [],
      variables: [],
      selectedNodeId: null,
      nextIdCounter: { start: 1, llm: 1, tool: 1, end: 1 },
    }),
}))
