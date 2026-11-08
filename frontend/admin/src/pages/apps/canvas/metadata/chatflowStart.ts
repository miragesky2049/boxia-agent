import { useSyncExternalStore } from 'react'
import type { FlowType } from '../../../../api/apps'

// 对话流（chatflow）开始节点内置启动参数：对齐 Coze 的 USER_INPUT / CONVERSATION_NAME。
// 内置参数只在 UI 上派生展示，不写入画布 JSON（config.inputs 只存手动参数）；
// 运行时由后端 chat_service 每轮注入并经 START 节点透传为 outputs。

export interface StartParamItem {
  name: string
  type: string
  required: boolean
  builtin?: boolean
}

export const CHATFLOW_START_BUILTIN_PARAMS: StartParamItem[] = [
  { name: 'USER_INPUT', type: 'string', required: false, builtin: true },
  { name: 'CONVERSATION_NAME', type: 'string', required: false, builtin: true },
]

const TYPE_SHORT_LABELS: Record<string, string> = {
  string: 'str',
  number: 'num',
  boolean: 'bool',
  object: 'obj',
  file: 'file',
  image: 'image',
  'array[string]': 'arr[str]',
  'array[number]': 'arr[num]',
  'array[object]': 'arr[obj]',
}

export function typeShortLabel(type: string): string {
  const key = String(type || 'string').toLowerCase()
  return TYPE_SHORT_LABELS[key] || key
}

function parseManualParams(raw: unknown): StartParamItem[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((item: any, idx: number) => ({
      name: String(item?.name ?? item?.variableName ?? `param_${idx + 1}`),
      type: String(item?.type ?? item?.variableType ?? 'string'),
      required: Boolean(item?.required),
    }))
    .filter((item) => item.name)
}

// 开始节点「启动参数」的完整视图：chatflow 下内置两行在前，手动参数在后；
// 导入图里若存有与内置同名的手动参数则去重，避免卡片/引用器出现重复行
export function listStartInputParams(configInputs: unknown, flowType?: FlowType): StartParamItem[] {
  const manual = parseManualParams(configInputs)
  if (flowType !== 'chatflow') {
    // 工作流形态隐藏对话流专属参数（导入图可能把同名内置参数持久化进了节点数据）
    return manual.filter((p) => !isChatflowBuiltinParamName(p.name))
  }
  return [
    ...CHATFLOW_START_BUILTIN_PARAMS,
    ...manual.filter((p) => !isChatflowBuiltinParamName(p.name)),
  ]
}

const CHATFLOW_BUILTIN_PARAM_NAMES = new Set(CHATFLOW_START_BUILTIN_PARAMS.map((p) => p.name))

/** 名称是否为对话流专属的内置启动参数（USER_INPUT / CONVERSATION_NAME） */
export function isChatflowBuiltinParamName(name: unknown): boolean {
  return CHATFLOW_BUILTIN_PARAM_NAMES.has(String(name ?? ''))
}

/**
 * 过滤列表中的对话流专属内置参数：workflow 形态下隐藏，chatflow 形态原样返回。
 * 仅影响 UI 展示；落库由上层（输出编辑器保存路径）原样回填，保持非破坏性。
 */
export function filterBuiltinStartParams<T extends { name?: unknown }>(
  items: T[],
  flowType?: FlowType,
): T[] {
  if (flowType === 'chatflow') return items
  return items.filter((item) => !isChatflowBuiltinParamName(item?.name))
}

// ========== 画布形态响应式 store ==========
// FlowGram 节点渲染组件在注册表构建时以闭包捕获 flowType，已挂载节点不一定随
// prop 更新重渲染；切换形态后经外部 store 驱动卡片内部（输入芯片行、副标题）刷新。

let currentFlowType: FlowType = 'workflow'
const flowTypeListeners = new Set<() => void>()

export const flowTypeStore = {
  /** 同步当前画布形态并通知订阅者（值不变时不触发） */
  set(flowType: FlowType) {
    if (currentFlowType === flowType) return
    currentFlowType = flowType
    flowTypeListeners.forEach((listener) => listener())
  },
  get(): FlowType {
    return currentFlowType
  },
  subscribe(listener: () => void): () => void {
    flowTypeListeners.add(listener)
    return () => {
      flowTypeListeners.delete(listener)
    }
  },
}

/** 在 React 组件内读取当前画布形态，切换时自动重渲染 */
export function useFlowType(): FlowType {
  return useSyncExternalStore(flowTypeStore.subscribe, flowTypeStore.get)
}
