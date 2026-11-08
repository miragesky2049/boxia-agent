import { describe, expect, it } from 'vitest'
import type { WorkflowJSON } from '@flowgram.ai/free-layout-editor'
import {
  DEFAULT_GRAPH,
  DEFAULT_SCHEMA_VERSION,
  fromCozeIR,
  readSchemaVersion,
  toCozeIR,
} from './cozeIR'

const keyToCozeType = { start: '1', llm: '3', loop: '21' }
const cozeTypeToKey = { '1': 'start', '3': 'llm', '21': 'loop' }

const flowgram: WorkflowJSON = {
  nodes: [
    {
      id: 'start-1',
      type: 'start',
      meta: { position: { x: 10, y: 20 } },
      data: { title: '开始', config: { inputs: [{ name: 'q' }] } },
    },
    {
      id: 'llm-1',
      type: 'llm',
      meta: { position: { x: 300, y: 20 } },
      data: { title: '大模型', config: { model: 'gpt' }, outputs: [{ name: 'text' }] },
    },
  ],
  edges: [
    {
      id: 'e1',
      sourceNodeID: 'start-1',
      targetNodeID: 'llm-1',
      sourcePortID: 'default',
      targetPortID: 'input',
    },
  ],
} as unknown as WorkflowJSON

describe('cozeIR adapter', () => {
  it('toCozeIR 把 type_key 映射回 type_code 并保留坐标与配置', () => {
    const ir = toCozeIR(flowgram, keyToCozeType) as any
    expect(ir.nodes[0]).toMatchObject({
      id: 'start-1',
      type: '1',
      meta: { position: { x: 10, y: 20 } },
      data: { nodeMeta: { title: '开始' } },
    })
    expect(ir.nodes[1].data.inputs.model).toBe('gpt')
    expect(ir.edges[0]).toMatchObject({
      id: 'e1',
      sourceNodeID: 'start-1',
      targetNodeID: 'llm-1',
      sourcePortID: 'default',
      targetPortID: 'input',
    })
  })

  it('schema_version 默认值与显式值都会透传', () => {
    expect((toCozeIR(flowgram, keyToCozeType) as any).schema_version).toBe(DEFAULT_SCHEMA_VERSION)
    expect((toCozeIR(flowgram, keyToCozeType, 7) as any).schema_version).toBe(7)
    expect(readSchemaVersion({ schema_version: '3' })).toBe(3)
    expect(readSchemaVersion({})).toBe(DEFAULT_SCHEMA_VERSION)
    expect(readSchemaVersion(null)).toBe(DEFAULT_SCHEMA_VERSION)
  })

  it('fromCozeIR 把 type_code 映射回 type_key 并保留 schema 之外的数据', () => {
    const coze = {
      schema_version: 5,
      nodes: [
        {
          id: 'n1',
          type: '3',
          meta: { position: { x: 1, y: 2 } },
          data: { nodeMeta: { title: 'LLM' }, inputs: { model: 'x' }, outputs: [{ name: 'text' }] },
        },
      ],
      edges: [{ id: 'e1', sourceNodeID: 'n1', targetNodeID: 'n2', sourcePortID: 'true' }],
    }
    const result = fromCozeIR(coze, cozeTypeToKey)
    expect(result.nodes[0]).toMatchObject({
      id: 'n1',
      type: 'llm',
      meta: { position: { x: 1, y: 2 } },
      data: { title: 'LLM', config: { model: 'x' }, outputs: [{ name: 'text' }] },
    })
    expect(result.edges[0]).toMatchObject({
      id: 'e1',
      sourceNodeID: 'n1',
      targetNodeID: 'n2',
      sourcePortID: 'true',
    })
    expect(readSchemaVersion(coze)).toBe(5)
  })

  it('未知数字类型原样保留 type，避免节点丢失', () => {
    const result = fromCozeIR({ nodes: [{ id: 'n1', type: '99', data: {} }] }, cozeTypeToKey)
    expect(result.nodes[0]!.type).toBe('99')
  })

  it('空图回落 DEFAULT_GRAPH', () => {
    expect(fromCozeIR(null, cozeTypeToKey)).toBe(DEFAULT_GRAPH)
    expect(fromCozeIR({ nodes: [] }, cozeTypeToKey)).toBe(DEFAULT_GRAPH)
    expect(DEFAULT_GRAPH.nodes?.[0]?.type).toBe('start')
  })

  it('y > 1000 的脏位置会被重置', () => {
    const result = fromCozeIR(
      { nodes: [{ id: 'n1', type: '3', meta: { position: { x: 50, y: 2000 } }, data: {} }] },
      cozeTypeToKey,
    )
    expect(result.nodes[0]!.meta).toEqual({ position: { x: 200, y: 200 } })
  })

  it('子图节点 blocks/edges 递归还原为 data.subgraph', () => {
    const coze = {
      nodes: [
        {
          id: 'loop-1',
          type: '21',
          data: {},
          blocks: [{ id: 'inner-1', type: '1', data: { nodeMeta: { title: '入口' } } }],
          edges: [],
        },
      ],
    }
    const result = fromCozeIR(coze, cozeTypeToKey)
    const subgraph = (result.nodes[0]!.data as any).subgraph as WorkflowJSON
    expect(subgraph.nodes?.[0]).toMatchObject({ id: 'inner-1', type: 'start' })
  })

  describe('分支端口归一化', () => {
    const branchTypes = { '1': 'start', '3': 'llm', '8': 'if_else' }
    const ifElseNode = (cases?: unknown) => ({
      id: 'if-1',
      type: '8',
      data: { inputs: cases === undefined ? {} : { cases } },
    })

    it('空 cases 补一个默认「如果」', () => {
      const result = fromCozeIR({ nodes: [ifElseNode()] }, branchTypes)
      const config = (result.nodes[0]!.data as any).config
      expect(config.cases).toHaveLength(1)
      expect(config.cases[0].case_id).toBe('case_1')
    })

    it('未知端口优先占用空闲分支口，已占用时落到 else', () => {
      const result = fromCozeIR(
        {
          nodes: [
            ifElseNode([{ case_id: 'case_1', left: '{{start.x}}', operator: 'eq', right: '1' }]),
            { id: 'out-1', type: '3', data: {} },
            { id: 'out-2', type: '3', data: {} },
          ],
          edges: [
            { id: 'e1', sourceNodeID: 'if-1', targetNodeID: 'out-1', sourcePortID: 'case_1' },
            { id: 'e2', sourceNodeID: 'if-1', targetNodeID: 'out-2', sourcePortID: 'true' },
          ],
        },
        branchTypes,
      )
      expect(result.edges[0]!.sourcePortID).toBe('case_1')
      expect(result.edges[1]!.sourcePortID).toBe('else')
    })

    it('false 端口直接映射到 else，不影响已有分支口', () => {
      const result = fromCozeIR(
        {
          nodes: [
            ifElseNode([{ case_id: 'case_1', left: '{{start.x}}', operator: 'eq', right: '1' }]),
            { id: 'out-1', type: '3', data: {} },
          ],
          edges: [{ id: 'e1', sourceNodeID: 'if-1', targetNodeID: 'out-1', sourcePortID: 'false' }],
        },
        branchTypes,
      )
      expect(result.edges[0]!.sourcePortID).toBe('else')
    })

    it('同一端口不会被重复占用', () => {
      const result = fromCozeIR(
        {
          nodes: [
            ifElseNode([
              { case_id: 'case_1', left: '{{start.x}}', operator: 'eq', right: '1' },
              { case_id: 'case_2', left: '{{start.x}}', operator: 'eq', right: '2' },
            ]),
            { id: 'out-1', type: '3', data: {} },
            { id: 'out-2', type: '3', data: {} },
          ],
          edges: [
            { id: 'e1', sourceNodeID: 'if-1', targetNodeID: 'out-1', sourcePortID: 'case_1' },
            { id: 'e2', sourceNodeID: 'if-1', targetNodeID: 'out-2', sourcePortID: 'true' },
          ],
        },
        branchTypes,
      )
      expect(result.edges[1]!.sourcePortID).toBe('case_2')
    })
  })

  it('子图节点 toCozeIR 输出 blocks/edges 而不是嵌套 data', () => {
    const withSubgraph = {
      nodes: [
        {
          id: 'loop-1',
          type: 'loop',
          data: { subgraph: { nodes: [{ id: 'inner-1', type: 'start', data: {} }], edges: [] } },
        },
      ],
      edges: [],
    } as unknown as WorkflowJSON
    const ir = toCozeIR(withSubgraph, keyToCozeType) as any
    expect(ir.nodes[0].type).toBe('21')
    expect(ir.nodes[0].blocks[0]).toMatchObject({ id: 'inner-1', type: '1' })
    expect(ir.nodes[0].edges).toEqual([])
  })
})
