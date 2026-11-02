import { useCallback, useEffect, useMemo, useState } from 'react';
import { WorkflowNodeRenderer } from '@flowgram.ai/free-layout-editor';
import type { WorkflowNodeEntity } from '@flowgram.ai/free-layout-editor';
import type { NodeMeta } from '../../../api/nodeMeta';
import { resolveCapabilities } from '../canvas/metadata/capabilities';
import { NodeCard, type NodeCardAction, type DynamicOutputPort } from './NodeCard';
import { parseCasesValue } from './NodeConfigForm';

// 卡片「⋯」菜单回调：按节点粒度操作，不依赖画布当前选中态
export interface NodeCardActions {
  onRename: (node: WorkflowNodeEntity) => void;
  onCopy: (node: WorkflowNodeEntity) => void;
  onDelete: (node: WorkflowNodeEntity) => void;
}

// FlowGram 未导出端口实体类型，这里只声明动态端口逻辑用到的最小结构
interface WorkflowPortLike {
  portType?: string;
  portID?: string;
  dispose?: () => void;
}

interface WorkflowNodePortsDataLike {
  updateDynamicPorts?: () => void;
  allPorts?: WorkflowPortLike[];
}

// 等待 React 提交 DOM + FlowGram 创建端口实体后再重扫
const DYNAMIC_PORT_RESCAN_DELAY_MS = 50;

// ========== 节点渲染组件（双击打开配置） ==========
export function makeNodeRenderer(
  meta: NodeMeta,
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

    // if_else 节点：根据 config.cases 动态生成出口端口（每个 case 一个出口 + 否则出口）
    // FlowGram 的 useDynamicPort 机制会扫描节点 DOM 中的 [data-port-id] 元素，自动注册为可拖拽端口
    const dynamicOutputs = useMemo<DynamicOutputPort[] | undefined>(() => {
      if (meta.type_key !== 'if_else') return undefined;
      const cases = parseCasesValue(nodeData.config?.cases);
      const ports: DynamicOutputPort[] = cases.map((c, idx) => ({
        portID: c.case_id,
        label: idx === 0 ? '如果 1' : `否则，如果 ${idx + 1}`,
      }));
      ports.push({ portID: 'else', label: '否则' });
      return ports;
    }, [nodeData.config?.cases]);

    // if_else 节点：cases 变化时触发 FlowGram 重新扫描 DOM 中的 [data-port-id] 端口
    // useDynamicPort 模式下，FlowGram 只在 SizeData.onDataChange 时自动调用 updateDynamicPorts
    // 我们需要手动触发，确保新增/删除 case 后端口位置立刻更新
    useEffect(() => {
      if (meta.type_key !== 'if_else' || !dynamicOutputs) return;
      const timer = window.setTimeout(() => {
        // 遍历 dataManager 找到 WorkflowNodePortsData 实例
        // FlowGram 的 dataManager 是 Map，key 是 Registry.type 字符串
        const dm = (node as unknown as { dataManager?: { get?: (type: string) => unknown } }).dataManager;
        if (!dm?.get) return;
        const portsData = dm.get('WorkflowNodePortsData') as WorkflowNodePortsDataLike | undefined;
        if (!portsData || typeof portsData.updateDynamicPorts !== 'function') return;
        portsData.updateDynamicPorts();
        // 清理历史残留输出端口（旧 IR 反序列化时按 true/false 静态端口注册的实体）
        // 预期输出端口 = 动态渲染的 case_id 列表 + 'else'；其余 output 实体 dispose 掉，
        // 避免在节点右缘中部多出一个无 targetElement 的悬浮端点
        const expected = new Set(dynamicOutputs.map((p) => p.portID));
        portsData.allPorts?.forEach((port) => {
          if (port.portType === 'output' && (port.portID == null || !expected.has(port.portID))) {
            port.dispose?.();
          }
        });
      }, DYNAMIC_PORT_RESCAN_DELAY_MS);
      return () => window.clearTimeout(timer);
    }, [dynamicOutputs, node]);

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

    // if_else 节点：不渲染统一的「在后面加节点」+ 按钮，分支已由各自端口独立连线
    const isIfElseNode = meta.type_key === 'if_else';
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
          onAddNext={!isIfElseNode && onAddNextToNode ? () => onAddNextToNode(node) : undefined}
          actions={actions}
          dynamicOutputs={dynamicOutputs}
        />
      </WorkflowNodeRenderer>
    );
  };
}
