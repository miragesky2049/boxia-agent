import type { FlowType } from '../../../../api/apps';
import type { NodeMeta } from '../../../../api/nodeMeta';

// 实机对齐 coze：工作流与对话流共用同一套节点库，不按 flow_type 裁剪节点。
// 差异只在开始/结束节点系统字段、试运行界面与运行语义，运行期冲突由后端拦截。
export function isNodeAvailable(_typeKey: string, _flowType: FlowType): boolean {
  return true;
}

export function filterNodeMetasByFlow(metas: NodeMeta[], _flowType?: FlowType): NodeMeta[] {
  return metas;
}

// 切换形态前的非破坏性提示：问答节点在工作流执行中没有恢复通道。
export function findFlowWarnings(
  nodes: Array<{ typeKey: string }>,
  nextFlowType: FlowType,
  keyToMeta: Record<string, NodeMeta>,
): string[] {
  if (nextFlowType !== 'workflow') return [];
  const warnings = new Set<string>();
  nodes.forEach((node) => {
    if (node.typeKey === 'question') {
      warnings.add(keyToMeta[node.typeKey]?.title || node.typeKey);
    }
  });
  return Array.from(warnings);
}
