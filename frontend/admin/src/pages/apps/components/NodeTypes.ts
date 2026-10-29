import type { NodeType } from '../store/appStore'

/** 连线中点 / 节点输出端口旁「+」可插入的节点类型 */
export const INSERTABLE_TYPES: Array<{ type: NodeType; label: string }> = [
  { type: 'llm', label: 'LLM' },
  { type: 'tool', label: '工具' },
  { type: 'template', label: '模板' },
  { type: 'http', label: 'HTTP' },
  { type: 'retrieval', label: '检索' },
  { type: 'branch', label: '条件分支' },
  { type: 'human_task', label: '人审' },
  { type: 'subgraph', label: '子图' },
]
