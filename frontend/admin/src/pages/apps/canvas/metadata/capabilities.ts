import type { NodeMeta } from '../../../../api/nodeMeta';

// 节点能力判断：优先读后端 meta.capabilities，缺失时用本地兜底。
// 页面与组件不再散落 typeKey === 'start' 这类判断。

export interface NodeCapabilitiesView {
  runnable: boolean;
  copyable: boolean;
  deletable: boolean;
  hasSubgraph: boolean;
  hasOutputs: boolean;
}

const DEFAULT_CAPABILITIES: NodeCapabilitiesView = {
  runnable: true,
  copyable: true,
  deletable: true,
  hasSubgraph: false,
  hasOutputs: true,
};

// 仅在后端元数据未加载时使用
const CAPABILITY_FALLBACK: Record<string, Partial<NodeCapabilitiesView>> = {
  start: { deletable: false },
  comment: { runnable: false, hasOutputs: false },
  note: { runnable: false, hasOutputs: false },
  break: { hasOutputs: false },
  continue: { hasOutputs: false },
  loop: { hasSubgraph: true },
  batch: { hasSubgraph: true },
  subworkflow: { hasSubgraph: true },
  update_conversation: { hasOutputs: false },
  delete_conversation: { hasOutputs: false },
  update_message: { hasOutputs: false },
  delete_message: { hasOutputs: false },
  clear_context: { hasOutputs: false },
};

export function resolveCapabilities(
  meta: NodeMeta | undefined,
  typeKey?: string,
): NodeCapabilitiesView {
  const declared = meta?.capabilities;
  const fallback = CAPABILITY_FALLBACK[typeKey || ''] || {};
  return {
    runnable: declared?.runnable ?? fallback.runnable ?? DEFAULT_CAPABILITIES.runnable,
    copyable: declared?.copyable ?? fallback.copyable ?? DEFAULT_CAPABILITIES.copyable,
    deletable: declared?.deletable ?? fallback.deletable ?? DEFAULT_CAPABILITIES.deletable,
    hasSubgraph: declared?.has_subgraph ?? fallback.hasSubgraph ?? DEFAULT_CAPABILITIES.hasSubgraph,
    hasOutputs: declared?.has_outputs ?? fallback.hasOutputs ?? DEFAULT_CAPABILITIES.hasOutputs,
  };
}

export function canRun(meta: NodeMeta | undefined, typeKey?: string): boolean {
  return resolveCapabilities(meta, typeKey).runnable;
}

export function canCopy(meta: NodeMeta | undefined, typeKey?: string): boolean {
  return resolveCapabilities(meta, typeKey).copyable;
}

export function canDelete(meta: NodeMeta | undefined, typeKey?: string): boolean {
  return resolveCapabilities(meta, typeKey).deletable;
}

export function hasSubgraph(meta: NodeMeta | undefined, typeKey?: string): boolean {
  return resolveCapabilities(meta, typeKey).hasSubgraph;
}

export function hasOutputs(meta: NodeMeta | undefined, typeKey?: string): boolean {
  return resolveCapabilities(meta, typeKey).hasOutputs;
}
