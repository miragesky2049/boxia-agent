import { describe, expect, it } from 'vitest'
import type { NodeMeta } from '../../../../api/nodeMeta'
import {
  buildCategoryGroups,
  groupFieldsByMetaGroup,
  resolveIcon,
  resolveNextRecommendations,
  resolveSubtitleHint,
} from './nodePresentation'

function makeMeta(partial: Partial<NodeMeta> & { type_key: string }): NodeMeta {
  return {
    type_code: '0',
    title: partial.type_key,
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
    },
    inputs: [],
    outputs: [],
    config_fields: [],
    ...partial,
  }
}

describe('nodePresentation', () => {
  it('图标与静态副标题直接取自后端元数据', () => {
    const meta = makeMeta({ type_key: 'llm', icon: '🤖', subtitle_hint: '大模型' })
    expect(resolveIcon(meta)).toBe('🤖')
    expect(resolveSubtitleHint(meta)).toBe('大模型')
    expect(resolveIcon(undefined)).toBe('')
    expect(resolveSubtitleHint(undefined)).toBe('')
  })

  it('分类分组按固定顺序输出，空分类与未知分类末尾追加', () => {
    const metas = [
      makeMeta({ type_key: 'a', category: 'misc' }),
      makeMeta({ type_key: 'b', category: 'control' }),
      makeMeta({ type_key: 'c', category: 'custom' }),
    ]
    const groups = buildCategoryGroups(metas)
    expect(groups.map((g) => g.key)).toEqual(['control', 'misc', 'custom'])
    expect(groups[2]!.label).toBe('custom')
    expect(buildCategoryGroups(metas, (m) => m.type_key !== 'b').map((g) => g.key)).toEqual([
      'misc',
      'custom',
    ])
  })

  it('后端分组全部为空时返回 null，交由本地兜底', () => {
    const fields = [
      {
        name: 'a',
        label: 'A',
        field_type: 'text',
        options: [],
        default: '',
        required: false,
        placeholder: '',
        description: '',
        group: '',
      },
    ]
    expect(groupFieldsByMetaGroup(fields)).toBeNull()
  })

  it('后端分组存在时按出现顺序分组，空分组归入其他', () => {
    const base = {
      field_type: 'text',
      options: [],
      default: '',
      required: false,
      placeholder: '',
      description: '',
    }
    const fields = [
      { ...base, name: 'a', label: 'A', group: '基础' },
      { ...base, name: 'b', label: 'B', group: '' },
      { ...base, name: 'c', label: 'C', group: '基础' },
    ]
    const sections = groupFieldsByMetaGroup(fields)
    expect(sections?.map((s) => s.title)).toEqual(['基础', '其他'])
    expect(sections?.[0]!.fields.map((f) => f.name)).toEqual(['a', 'c'])
  })

  it('下一步推荐优先使用后端声明并解析标题', () => {
    const keyToMeta = {
      llm: makeMeta({ type_key: 'llm', title: '大模型' }),
      end: makeMeta({ type_key: 'end', title: '结束' }),
    }
    const meta = makeMeta({ type_key: 'start', next_recommendations: ['llm', 'end'] })
    expect(resolveNextRecommendations(meta, keyToMeta)).toEqual([
      { typeKey: 'llm', label: '大模型' },
      { typeKey: 'end', label: '结束' },
    ])
  })

  it('后端未给推荐时回落本地兜底，未知类型返回空', () => {
    const keyToMeta = { llm: makeMeta({ type_key: 'llm', title: '大模型' }) }
    const meta = makeMeta({ type_key: 'start' })
    expect(resolveNextRecommendations(meta, keyToMeta)[0]).toEqual({
      typeKey: 'llm',
      label: '大模型',
    })
    expect(resolveNextRecommendations(undefined, keyToMeta, 'unknown')).toEqual([])
  })
})
