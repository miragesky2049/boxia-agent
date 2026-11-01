import { useCallback, useEffect, useState, type MutableRefObject } from 'react';
import { WorkflowNodeRenderer } from '@flowgram.ai/free-layout-editor';
import type { WorkflowNodeEntity, FreeLayoutPluginContext } from '@flowgram.ai/free-layout-editor';
import type { NodeMeta } from '../../../api/nodeMeta';
import { resolveCapabilities } from '../canvas/metadata/capabilities';
import { NodeCard, type NodeCardAction } from './NodeCard';

// 卡片「⋯」菜单回调：按节点粒度操作，不依赖画布当前选中态
export interface NodeCardActions {
  onRename: (node: WorkflowNodeEntity) => void;
  onCopy: (node: WorkflowNodeEntity) => void;
  onDelete: (node: WorkflowNodeEntity) => void;
}

// ========== 节点渲染组件（双击打开配置） ==========
export function makeNodeRenderer(
  meta: NodeMeta,
  _ctxRef: MutableRefObject<FreeLayoutPluginContext | null>,
  onNodeDoubleClick: (node: WorkflowNodeEntity) => void,
  onAddNextToNode?: (node: WorkflowNodeEntity) => void,
  cardActions?: NodeCardActions,
) {
  return function NodeRenderer({ node }: { node: WorkflowNodeEntity }) {
    // FlowGram 把节点 data 存在 extInfo 里（node.data 是空对象），且需订阅变更才能重渲染
    const readExtInfo = useCallback(() => {
      const entity = node as unknown as { getExtInfo?: () => Record<string, any> | undefined };
      return entity.getExtInfo?.() || {};
    }, [node]);
    const [nodeData, setNodeData] = useState<Record<string, any>>(readExtInfo);
    useEffect(() => {
      const event = (node as unknown as { onExtInfoChange?: unknown }).onExtInfoChange as
        | ((fn: (e: { newInfo?: Record<string, any> }) => void) => { dispose?: () => void })
        | undefined;
      if (!event) return;
      const disposable = event((e) => setNodeData(e?.newInfo || readExtInfo()));
      return () => disposable?.dispose?.();
    }, [node, readExtInfo]);
    const title = nodeData.title || meta.title;

    // Comment / Note 便签：黄色便签块，显示 content 文本，不显示端口和节点按钮样式
    if (meta.type_key === 'comment' || meta.type_key === 'note') {
      const content = String(nodeData.config?.content || nodeData.content || title || '双击编辑便签');
      return (
        <WorkflowNodeRenderer node={node}>
          <div
            onDoubleClick={() => onNodeDoubleClick(node)}
            style={{
              padding: '12px 14px',
              background: '#fff9c4',
              color: '#5d4037',
              borderRadius: 2,
              fontSize: 13,
              lineHeight: 1.5,
              width: 200,
              minHeight: 80,
              cursor: 'pointer',
              userSelect: 'none',
              boxShadow: '2px 2px 6px rgba(0,0,0,0.15)',
              borderLeft: '3px solid #fbc02d',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {content}
          </div>
        </WorkflowNodeRenderer>
      );
    }

    // 菜单项按能力声明裁剪，后端新增节点无需在此改判断
    const capabilities = resolveCapabilities(meta, meta.type_key);
    const actions: NodeCardAction[] = [];
    if (cardActions?.onRename) {
      actions.push({ key: 'rename', label: '重命名', onClick: () => cardActions.onRename(node) });
    }
    if (cardActions?.onCopy && capabilities.copyable) {
      actions.push({ key: 'copy', label: '复制节点', onClick: () => cardActions.onCopy(node) });
    }
    if (cardActions?.onDelete && capabilities.deletable) {
      actions.push({ key: 'delete', label: '删除', danger: true, onClick: () => cardActions.onDelete(node) });
    }

    return (
      <WorkflowNodeRenderer node={node}>
        <NodeCard
          typeKey={meta.type_key}
          color={meta.color}
          icon={meta.icon}
          title={title}
          config={nodeData.config}
          subtitleHint={meta.subtitle_hint}
          onDoubleClick={() => onNodeDoubleClick(node)}
          onAddNext={onAddNextToNode ? () => onAddNextToNode(node) : undefined}
          actions={actions}
        />
      </WorkflowNodeRenderer>
    );
  };
}
