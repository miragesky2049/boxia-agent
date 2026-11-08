import { describe, expect, it } from 'vitest'
import type { NodeCapabilities, NodeMeta } from '../../../../api/nodeMeta'
import { canCopy, canDelete, hasOutputs, hasSubgraph, resolveCapabilities } from './capabilities'

function makeMeta(typeKey: string, capabilities: Partial<NodeCapabilities> = {}): NodeMeta {
  return {
    type_code: '0',
    type_key: typeKey,
    title: typeKey,
    color: '#000000',
    category: 'misc',
    description: '',
    icon: '',
    subtitle_hint: '',
    next_recommendations: [],
    capabilities: {
      runnable: true,
      copyable: true,
      deletable: true,
      has_subgraph: false,
      has_outputs: true,
      ...capabilities,
    },
    inputs: [],
    outputs: [],
    config_fields: [],
  }
}

describe('resolveCapabilities', () => {
  it('后端声明优先于本地兜底', () => {
    const meta = makeMeta('start', { deletable: true })
    expect(resolveCapabilities(meta, 'start').deletable).toBe(true)
  })

  it('后端声明 false 不被默认值覆盖', () => {
    const meta = makeMeta('note', { runnable: false, has_outputs: false })
    const caps = resolveCapabilities(meta, 'note')
    expect(caps.runnable).toBe(false)
    expect(caps.hasOutputs).toBe(false)
  })

  it('元数据缺失时使用本地兜底', () => {
    expect(canDelete(undefined, 'start')).toBe(false)
    // start/end 为画布系统节点：start 不可复制，end 同样不可复制
    expect(canCopy(undefined, 'start')).toBe(false)
    expect(canCopy(undefined, 'end')).toBe(false)
    expect(resolveCapabilities(undefined, 'comment')).toMatchObject({
      runnable: false,
      hasOutputs: false,
    })
    expect(hasSubgraph(undefined, 'loop')).toBe(true)
    expect(hasSubgraph(undefined, 'batch')).toBe(true)
    expect(hasSubgraph(undefined, 'subworkflow')).toBe(true)
    expect(hasOutputs(undefined, 'break')).toBe(false)
    expect(hasOutputs(undefined, 'clear_context')).toBe(false)
  })

  it('未知类型回落默认能力', () => {
    expect(resolveCapabilities(undefined, 'unknown')).toEqual({
      runnable: true,
      copyable: true,
      deletable: true,
      hasSubgraph: false,
      hasOutputs: true,
    })
    expect(resolveCapabilities(undefined)).toEqual(resolveCapabilities(undefined, 'unknown'))
  })
})
