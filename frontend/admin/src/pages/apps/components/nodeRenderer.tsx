import { useCallback, useEffect, useMemo, useState } from 'react';
import { WorkflowNodeRenderer } from '@flowgram.ai/free-layout-editor';
import type { WorkflowNodeEntity } from '@flowgram.ai/free-layout-editor';
import type { NodeMeta } from '../../../api/nodeMeta';
import { resolveCapabilities } from '../canvas/metadata/capabilities';
import { listStartInputParams, useFlowType } from '../canvas/metadata/chatflowStart';
import { NodeCard, type NodeCardAction, type DynamicOutputPort } from './NodeCard';
import { parseCasesValue, parseIntentsValue } from './NodeConfigForm';

// 卡片「⋯」菜单回调：按节点粒度操作，不依赖画布当前选中态
export interface NodeCardActions {
  onRename: (node: WorkflowNodeEntity) => void;
  onCopy: (node: WorkflowNodeEntity) => void;
  onDelete: (node: WorkflowNodeEntity) => void;
}

interface WorkflowNodePortsDataLike {
  updateDynamicPorts?: () => void;
}

// 等待 React 提交 DOM + FlowGram 创建端口实体后再重扫
const DYNAMIC_PORT_RESCAN_DELAY_MS = 50;
// 卡片高度变化（新增/删除分支行）会晚于首次提交，再补一次
const DYNAMIC_PORT_RESCAN_SECOND_DELAY_MS = 200;

// ========== 节点渲染组件（双击打开配置） ==========
export function makeNodeRenderer(
  meta: NodeMeta,
  onNodeDoubleClick: (node: WorkflowNodeEntity) => void,
  onAddNextToNode?: (node: WorkflowNodeEntity) => void,
  cardActions?: NodeCardActions,
) {
  return function NodeRenderer({ node }: { node: WorkflowNodeEntity }) {
    // 画布形态从外部 store 读取：注册表以闭包捕获的 prop 在切换后不会刷新已挂载节点
    const liveFlowType = useFlowType();
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

    // 对话流开始节点：卡片显示「输入」芯片行（内置 USER_INPUT/CONVERSATION_NAME + 兼容导入图残留的手动同名参数）
    const inputChips = useMemo<Array<{ type: string; name: string }> | undefined>(() => {
      if (meta.type_key !== 'start' || liveFlowType !== 'chatflow') return undefined;
      return listStartInputParams(nodeData.config?.inputs, liveFlowType).map((p) => ({ type: p.type, name: p.name }));
    }, [meta.type_key, liveFlowType, nodeData.config?.inputs]);

    // 分支节点：根据配置动态生成出口端口
    // - if_else：每个 case 一个出口 + 否则出口
    // - intent：每个意图一个出口 + 其他出口
    // FlowGram 的 useDynamicPort 机制会扫描节点 DOM 中的 [data-port-id] 元素，自动注册为可拖拽端口
    const isDynamicBranchNode = meta.type_key === 'if_else' || meta.type_key === 'intent';
    const dynamicOutputs = useMemo<DynamicOutputPort[] | undefined>(() => {
      if (meta.type_key === 'if_else') {
        const cases = parseCasesValue(nodeData.config?.cases);
        const ports: DynamicOutputPort[] = cases.map((c, idx) => ({
          portID: c.case_id,
          label: idx === 0 ? '如果 1' : `否则，如果 ${idx + 1}`,
        }));
        ports.push({ portID: 'else', label: '否则' });
        return ports;
      }
      if (meta.type_key === 'intent') {
        const intents = parseIntentsValue(nodeData.config?.intents);
        const ports: DynamicOutputPort[] = intents.map((it, idx) => ({
          portID: String(it.id),
          label: it.name || `意图 ${idx + 1}`,
        }));
        ports.push({ portID: '0', label: '其他' });
        return ports;
      }
      return undefined;
    }, [meta.type_key, nodeData.config?.cases, nodeData.config?.intents]);

    // if_else / intent 节点：配置变化后触发 FlowGram 重新扫描 DOM 中的 [data-port-id] 端口。
    // useDynamicPort 模式下 FlowGram 只在 SizeData.onDataChange 时自动同步，这里补一次保证及时。
    // 不要在外部手动 dispose 端口：WorkflowPortEntity.dispose() 会连带 dispose 端口上的连线，
    // 而旧端口的清理已经由 IR 归一化（branchPorts）在加载阶段完成。
    useEffect(() => {
      if (!isDynamicBranchNode || !dynamicOutputs) return;
      // 遍历 dataManager 找到 WorkflowNodePortsData 实例
      // FlowGram 的 dataManager 是 Map，key 是 Registry.type 字符串
      const dm = (node as unknown as { dataManager?: { get?: (type: string) => unknown } }).dataManager;
      const portsData = dm?.get?.('WorkflowNodePortsData') as WorkflowNodePortsDataLike | undefined;
      if (!portsData || typeof portsData.updateDynamicPorts !== 'function') return;
      const sync = () => portsData.updateDynamicPorts?.();
      const first = window.setTimeout(sync, DYNAMIC_PORT_RESCAN_DELAY_MS);
      const second = window.setTimeout(sync, DYNAMIC_PORT_RESCAN_SECOND_DELAY_MS);
      return () => {
        window.clearTimeout(first);
        window.clearTimeout(second);
      };
    }, [dynamicOutputs, node, isDynamicBranchNode]);

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

    // 分支节点：不渲染统一的「在后面加节点」+ 按钮，分支已由各自端口独立连线
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
          onAddNext={!isDynamicBranchNode && onAddNextToNode ? () => onAddNextToNode(node) : undefined}
          actions={actions}
          dynamicOutputs={dynamicOutputs}
          inputChips={inputChips}
          flowType={liveFlowType}
        />
      </WorkflowNodeRenderer>
    );
  };
}
