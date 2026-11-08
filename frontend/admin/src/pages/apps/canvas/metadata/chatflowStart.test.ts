import { describe, expect, it, vi } from 'vitest'
import {
  CHATFLOW_START_BUILTIN_PARAMS,
  filterBuiltinStartParams,
  flowTypeStore,
  isChatflowBuiltinParamName,
  listStartInputParams,
  typeShortLabel,
} from './chatflowStart'

describe('chatflowStart 内置启动参数', () => {
  it('对话流形态返回 USER_INPUT/CONVERSATION_NAME 两个内置参数并标记 builtin', () => {
    const params = listStartInputParams([], 'chatflow')
    expect(params.map((p) => p.name)).toEqual(['USER_INPUT', 'CONVERSATION_NAME'])
    expect(params.every((p) => p.builtin)).toBe(true)
    expect(params.every((p) => p.type === 'string' && !p.required)).toBe(true)
  })

  it('工作流形态不注入内置参数，仅返回手动参数', () => {
    const manual = [{ name: 'q', type: 'string', required: true }]
    expect(listStartInputParams(manual, 'workflow')).toEqual(manual)
    expect(listStartInputParams(manual)).toEqual(manual)
  })

  it('对话流下内置参数在前、手动参数在后，并与同名手动参数去重', () => {
    const manual = [
      { name: 'USER_INPUT', type: 'string' },
      { name: 'extra', type: 'number' },
    ]
    const merged = listStartInputParams(manual, 'chatflow')
    expect(merged.map((p) => p.name)).toEqual(['USER_INPUT', 'CONVERSATION_NAME', 'extra'])
    expect(merged.find((p) => p.name === 'USER_INPUT')?.builtin).toBe(true)
    expect(merged.find((p) => p.name === 'extra')?.builtin).toBeUndefined()
  })

  it('脏数据容错：非数组返回仅内置，缺名条目按 param_N 兜底、空名被过滤', () => {
    expect(listStartInputParams(undefined, 'chatflow').map((p) => p.name)).toEqual(
      CHATFLOW_START_BUILTIN_PARAMS.map((p) => p.name),
    )
    expect(
      listStartInputParams([{ type: 'string' }, { name: '' }], 'workflow').map((p) => p.name),
    ).toEqual(['param_1'])
  })

  it('typeShortLabel 输出芯片用类型缩写', () => {
    expect(typeShortLabel('string')).toBe('str')
    expect(typeShortLabel('array[string]')).toBe('arr[str]')
    expect(typeShortLabel('UnknownType')).toBe('unknowntype')
  })
})

describe('对话流专属参数随形态显隐', () => {
  it('工作流形态下手动参数里残留的同名内置参数被隐藏', () => {
    const residual = [
      { name: 'USER_INPUT', type: 'string' },
      { name: 'q', type: 'string' },
    ]
    expect(listStartInputParams(residual, 'workflow').map((p) => p.name)).toEqual(['q'])
  })

  it('filterBuiltinStartParams 仅在非对话流形态过滤内置名', () => {
    const outputs = [{ name: 'USER_INPUT' }, { name: 'CONVERSATION_NAME' }, { name: 'custom' }]
    expect(filterBuiltinStartParams(outputs, 'workflow').map((o) => o.name)).toEqual(['custom'])
    expect(filterBuiltinStartParams(outputs, 'chatflow')).toEqual(outputs)
    expect(isChatflowBuiltinParamName('USER_INPUT')).toBe(true)
    expect(isChatflowBuiltinParamName('custom')).toBe(false)
  })

  it('flowTypeStore 值变化时通知订阅者，值不变不通知', () => {
    const listener = vi.fn()
    const unsubscribe = flowTypeStore.subscribe(listener)
    flowTypeStore.set('chatflow')
    expect(flowTypeStore.get()).toBe('chatflow')
    expect(listener).toHaveBeenCalledTimes(1)
    flowTypeStore.set('chatflow')
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
    flowTypeStore.set('workflow')
    expect(listener).toHaveBeenCalledTimes(1)
  })
})
