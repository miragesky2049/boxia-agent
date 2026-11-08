import type { WorkflowJSON } from '@flowgram.ai/free-layout-editor'

import { normalizeBranchEdgePorts, normalizeIfElseCases } from './branchPorts'

// Coze IR ↔ FlowGram WorkflowJSON 的唯一转换层。
// 后端 `/admin/apps/{id}/graph` 收发的是 Coze 结构；FlowGram 编辑器内部用自己的 WorkflowJSON。
// 新增节点类型只依赖 type_key ↔ type_code 映射，不需要再改页面。

export const DEFAULT_SCHEMA_VERSION = 1

export const DEFAULT_GRAPH: WorkflowJSON = {
  nodes: [
    {
      id: 'start-1',
      type: 'start',
      meta: { position: { x: 200, y: 200 } },
      data: {},
    } as WorkflowJSON['nodes'][number],
  ],
  edges: [],
}

const SUBGRAPH_NODE_TYPES = new Set(['loop', 'batch', 'subworkflow'])

// 后端把 schema_version 存在独立列，同时也允许 IR 自带一份用于往返透传
export function readSchemaVersion(ir: unknown): number {
  const raw = ir as { schema_version?: unknown } | null | undefined
  const version = Number(raw?.schema_version)
  return Number.isFinite(version) && version > 0 ? version : DEFAULT_SCHEMA_VERSION
}

export function toCozeIR(
  flowgram: WorkflowJSON,
  keyToCozeType: Record<string, string>,
  schemaVersion: number = DEFAULT_SCHEMA_VERSION,
): Record<string, unknown> {
  const nodes = (flowgram.nodes || []).map((n) => {
    const cozeType = keyToCozeType[n.type as string] || n.type
    const data = (n.data || {}) as Record<string, unknown>
    const config = (data.config || {}) as Record<string, unknown>
    const out: Record<string, unknown> = {
      id: n.id,
      type: cozeType,
      meta: {
        position: (n.meta as { position?: { x: number; y: number } })?.position ?? { x: 0, y: 0 },
      },
      data: {
        nodeMeta: { title: data.title || '' },
        inputs: {
          inputParameters: (config.inputParameters || []) as Array<{
            name: string
            input: unknown
          }>,
          ...config,
        },
        outputs: (data.outputs || []) as unknown[],
      },
    }
    // 子图节点：把 node.data.subgraph (WorkflowJSON) 转成 blocks/edges
    if (SUBGRAPH_NODE_TYPES.has(String(n.type)) && data.subgraph) {
      const nested = toCozeIR(data.subgraph as WorkflowJSON, keyToCozeType)
      out.blocks = nested.nodes
      out.edges = nested.edges
    }
    return out
  })

  const edges = (flowgram.edges || []).map((e) => {
    // FlowGram 的边 JSON 字段就是 sourceNodeID/targetNodeID（见 WorkflowEdgeJSON）
    const edge = e as unknown as Record<string, unknown>
    return {
      id: (edge.id as string) || `edge-${Math.random().toString(36).slice(2, 8)}`,
      sourceNodeID: edge.sourceNodeID,
      targetNodeID: edge.targetNodeID,
      sourcePortID: edge.sourcePortID,
      targetPortID: edge.targetPortID,
    }
  })

  return { schema_version: schemaVersion, nodes, edges }
}

export function fromCozeIR(coze: unknown, cozeTypeToKey: Record<string, string>): WorkflowJSON {
  if (!coze || typeof coze !== 'object') return DEFAULT_GRAPH
  const raw = coze as {
    nodes?: Array<Record<string, unknown>>
    edges?: Array<Record<string, unknown>>
  }
  if (!Array.isArray(raw.nodes) || raw.nodes.length === 0) return DEFAULT_GRAPH

  const nodes = raw.nodes.map((n) => {
    const cozeType = String(n.type ?? '')
    const registryType = cozeTypeToKey[cozeType] || String(n.type || 'default')
    const data = (n.data || {}) as Record<string, unknown>
    const nodeMeta = (data.nodeMeta || {}) as { title?: string }
    const inputs = (data.inputs || {}) as Record<string, unknown>
    const rawPos = (n.meta as { position?: { x: number; y: number } })?.position ?? { x: 0, y: 0 }
    // 修正脏位置：如果节点在画布坐标 y > 1000（之前拖拽测试留下的），重置到合理位置
    const pos = rawPos.y > 1000 ? { x: 200, y: 200 } : rawPos
    // 条件分支必须始终至少有一个「如果」，否则卡片与抽屉只剩「否则」，
    // 动态端口也会退化成单个 else，历史边无处可落
    const config =
      registryType === 'if_else' ? { ...inputs, cases: normalizeIfElseCases(inputs.cases) } : inputs
    const out: WorkflowJSON['nodes'][number] = {
      id: String(n.id),
      type: registryType,
      meta: { position: pos },
      data: {
        title: nodeMeta.title,
        config,
        outputs: (data.outputs || []) as unknown[],
      },
    } as WorkflowJSON['nodes'][number]
    // 子图节点：blocks/edges 还原成 node.data.subgraph
    const blocks = Array.isArray(n.blocks) ? (n.blocks as Array<Record<string, unknown>>) : []
    const innerEdges = Array.isArray(n.edges) ? (n.edges as Array<Record<string, unknown>>) : []
    if (blocks.length > 0) {
      const subCoze = { nodes: blocks, edges: innerEdges }
      ;(out.data as Record<string, unknown>).subgraph = fromCozeIR(subCoze, cozeTypeToKey)
    }
    return out
  })

  // 回填给 FlowGram 时必须用 sourceNodeID/targetNodeID，否则编辑器识别不到连线
  const edges = (raw.edges || []).map((e) => ({
    id: String(e.id ?? `edge-${Math.random().toString(36).slice(2, 8)}`),
    sourceNodeID: e.sourceNodeID,
    targetNodeID: e.targetNodeID,
    sourcePortID: e.sourcePortID,
    targetPortID: e.targetPortID,
  })) as unknown as WorkflowJSON['edges']

  // 历史图里分支边可能还挂 true/false、classificationId 等旧端口，
  // 统一映射到当前动态端口，避免 FlowGram 为未知端口生成游离端点
  normalizeBranchEdgePorts(
    nodes.map((node) => ({
      id: node.id,
      typeKey: String(node.type),
      config: ((node.data as unknown as Record<string, unknown> | undefined)?.config ??
        {}) as Record<string, unknown>,
    })),
    edges as unknown as Array<Record<string, unknown>>,
  )

  return { nodes, edges }
}
