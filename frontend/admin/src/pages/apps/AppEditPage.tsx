import { FreeLayoutEditor, WorkflowNodeRenderer } from '@flowgram.ai/free-layout-editor';
import type {
  WorkflowNodeRegistry,
  WorkflowNodeEntity,
  WorkflowPortEntity,
  WorkflowLinesManager,
  WorkflowJSON,
  FreeLayoutPluginContext,
} from '@flowgram.ai/free-layout-editor';
import '@flowgram.ai/free-layout-editor/index.css';
import { useParams } from 'react-router-dom';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Drawer, Input, Button, Select, Tag, Space, Typography, InputNumber, Popover, Tree, Modal, Collapse, message, Upload, AutoComplete, Tooltip } from 'antd';
import type { UploadFile } from 'antd';
import type { TreeProps } from 'antd';
import { getAppGraph, saveAppGraph, debugRunAppStream, debugRunAppStreamResume, validateGraph, listGraphVersions, rollbackGraph, publishGraph, type GraphValidationIssue, type GraphVersionItem, type ApprovalInterruptPayload } from '../../api/apps';
import { ApiError } from '../../api/client';
import { getNodeMeta, type NodeMeta } from '../../api/nodeMeta';
import { listAvailableModels, type ModelCatalogItem } from '../../api/models';
import { listDatasets, type DatasetItem } from '../../api/datasets';
import { NodeCard, type NodeCardAction } from './components/NodeCard';
import { NodeIcon } from './components/NodeIcon';
import { CanvasToolbar } from './components/CanvasToolbar';
import { ResourceSidebar } from './components/ResourceSidebar';
import { EmptyCanvasWelcome } from './components/EmptyCanvasWelcome';
import { groupConfigFields } from './components/configSections';
import { VariablesDrawer } from './components/VariablesDrawer';
import { usePortTooltips } from './components/usePortTooltips';
import { CanvasContextMenu } from './components/CanvasContextMenu';
import { AddNodePopover } from './components/AddNodePopover';
import { MiniMap } from './components/MiniMap';
import { RefChipInput } from './components/RefChipInput';
import { CodeEditor } from './components/CodeEditor';
import { getNextRecommendations } from './components/nodeNextRecommendations';
import { canCopy, canDelete, hasOutputs, hasSubgraph, resolveCapabilities } from './canvas/metadata/capabilities';
import { AlignGuides } from './components/AlignGuides';
import { ParameterListEditor } from './components/ParameterListEditor';
import { ToolListEditor } from './components/ToolListEditor';
import { CANVAS_TOKENS } from './canvas/tokens';
import {
  clearSelection,
  createLine,
  createNodeByType,
  disposeLinesByIds,
  fitView,
  getLineFromMousePos,
  getNode,
  getNodeCount,
  getNodeExtInfo,
  getNodeFromMousePos,
  getNodeTypeKey,
  getPortFromMousePos,
  getScroll,
  getSelection,
  getViewport,
  getWorldPosFromMouseEvent,
  removeNode,
  redo,
  scrollToCanvasPoint,
  selectAllNodes,
  setScroll,
  subscribeHistory,
  subscribeSelection,
  subscribeViewport,
  toWorkflowJSON,
  undo,
  updateNodeExtInfo,
  worldToScreen,
  type FlowContext,
} from './canvas/adapters/flowgramContext';
import {
  DEFAULT_GRAPH,
  DEFAULT_SCHEMA_VERSION,
  fromCozeIR,
  readSchemaVersion,
  toCozeIR,
} from './canvas/adapters/cozeIR';

// ========== 运行时节点状态（用于高亮） ==========
type RunNodeStatus = 'running' | 'success' | 'error';

// ========== 变量引用选择器（B3） ==========
interface GraphNodeSummary {
  id: string;
  typeKey: string;
  title: string;
  config: Record<string, any>;
  position?: { x: number; y: number };
}

// 抽屉「输入」区：按入边反查上游节点可引用字段
interface UpstreamInputGroup {
  nodeId: string;
  nodeTitle: string;
  fields: Array<{ name: string; label: string }>;
}

function buildPickerTreeData(
  nodes: GraphNodeSummary[],
  currentNodeId: string | null,
  keyToMeta: Record<string, NodeMeta>,
): NonNullable<TreeProps['treeData']> {
  return nodes
    .filter((n) => n.id !== currentNodeId)
    .map((node) => {
      const meta = keyToMeta[node.typeKey];
      const portOutputs = (meta?.outputs || []).map((p) => ({
        key: `${node.id}.output.${p.name}`,
        title: p.label || p.name,
        isLeaf: true,
      }));
      // START 节点的 inputParameters 作为虚拟输出
      const startInputs =
        node.typeKey === 'start' && Array.isArray(node.config?.inputs)
          ? (node.config.inputs as Array<{ name: string }>).map((inp) => ({
              key: `${node.id}.output.${inp.name}`,
              title: `入参: ${inp.name}`,
              isLeaf: true,
            }))
          : [];
      return {
        key: node.id,
        title: node.title || meta?.title || node.id,
        children: [...portOutputs, ...startInputs],
      };
    });
}

// 把上游节点 outputs 拍平为 AutoComplete options（用于 IF 左值 / 类似字段）
function buildLeftValueOptions(
  nodes: GraphNodeSummary[],
  currentNodeId: string | null,
  keyToMeta: Record<string, NodeMeta>,
): { value: string; label: React.ReactNode }[] {
  const options: { value: string; label: React.ReactNode }[] = [];
  for (const node of nodes) {
    if (node.id === currentNodeId) continue;
    const meta = keyToMeta[node.typeKey];
    const nodeTitle = node.title || meta?.title || node.id;
    const portOutputs = meta?.outputs || [];
    for (const p of portOutputs) {
      const ref = `{{${node.id}.output.${p.name}}}`;
      options.push({
        value: ref,
        label: (
          <span>
            <span style={{ color: '#6b7280' }}>{nodeTitle}</span>
            <span style={{ color: '#9ca3af', margin: '0 4px' }}>/</span>
            <span>{p.label || p.name}</span>
          </span>
        ),
      });
    }
    if (node.typeKey === 'start' && Array.isArray(node.config?.inputs)) {
      for (const inp of node.config.inputs as Array<{ name: string }>) {
        const ref = `{{${node.id}.output.${inp.name}}}`;
        options.push({
          value: ref,
          label: (
            <span>
              <span style={{ color: '#6b7280' }}>{nodeTitle}</span>
              <span style={{ color: '#9ca3af', margin: '0 4px' }}>/</span>
              <span>入参: {inp.name}</span>
            </span>
          ),
        });
      }
    }
  }
  return options;
}

function RefPickerButton({
  nodes,
  currentNodeId,
  keyToMeta,
  onPick,
}: {
  nodes: GraphNodeSummary[];
  currentNodeId: string | null;
  keyToMeta: Record<string, NodeMeta>;
  onPick: (ref: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const treeData = useMemo(
    () => buildPickerTreeData(nodes, currentNodeId, keyToMeta),
    [nodes, currentNodeId, keyToMeta],
  );
  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      placement="bottomLeft"
      content={
        <div style={{ width: 300, maxHeight: 360, overflowY: 'auto' }}>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>选择要引用的字段</div>
          <Tree
            treeData={treeData}
            defaultExpandAll
            onSelect={(keys) => {
              const key = keys[0];
              if (typeof key === 'string' && key.includes('.output.')) {
                onPick(`{{${key}}}`);
                setOpen(false);
              }
            }}
          />
        </div>
      }
    >
      <Button size="small" type="text" style={{ fontSize: 12, padding: '0 4px' }}>
        {'{ }'} 引用
      </Button>
    </Popover>
  );
}

// 卡片「⋯」菜单回调：按节点粒度操作，不依赖画布当前选中态
interface NodeCardActions {
  onRename: (node: WorkflowNodeEntity) => void;
  onCopy: (node: WorkflowNodeEntity) => void;
  onDelete: (node: WorkflowNodeEntity) => void;
}

// ========== 节点渲染组件（双击打开配置） ==========
function makeNodeRenderer(
  meta: NodeMeta,
  _ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>,
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

// ========== 节点配置表单 ==========
type NodeConfigValues = Record<string, any>;

function FieldControl({
  field,
  value,
  onChange,
  picker,
  datasetOptions,
}: {
  field: {
    name: string;
    label: string;
    field_type: string;
    options: Array<{ value: string; label?: string }>;
    default: any;
    required: boolean;
    placeholder: string;
    description: string;
  };
  value: any;
  onChange: (name: string, value: any) => void;
  picker?: React.ReactNode;
  datasetOptions?: DatasetItem[];
}) {
  const current = value ?? field.default ?? '';

  switch (field.field_type) {
    case 'number':
      return (
        <InputNumber
          value={typeof current === 'number' ? current : Number(current) || 0}
          onChange={(v) => onChange(field.name, v ?? 0)}
          style={{ width: '100%' }}
        />
      );
    case 'select':
      return (
        <Select
          value={String(current || field.default || '')}
          onChange={(v) => onChange(field.name, v)}
          options={field.options.map((o) => ({ value: o.value, label: o.label || o.value }))}
          style={{ width: '100%' }}
        />
      );
    case 'boolean':
      return (
        <Select
          value={current ? 'true' : 'false'}
          onChange={(v) => onChange(field.name, v === 'true')}
          options={[{ value: 'true', label: '是' }, { value: 'false', label: '否' }]}
          style={{ width: '100%' }}
        />
      );
    case 'code_editor':
      return (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {picker}
          <CodeEditor
            value={String(current || '')}
            onChange={(next) => onChange(field.name, next)}
            placeholder={field.placeholder}
          />
        </Space>
      )
    case 'parameter_list':
      return (
        <ParameterListEditor
          value={current}
          onChange={(next) => onChange(field.name, next)}
        />
      )
    case 'tool_list':
      // tool_list 由 NodeConfigForm 外层用 ToolListEditor 渲染，FieldControl 不直接处理
      return <Input.TextArea rows={3} value={String(current || '')} disabled />;
    case 'textarea':
      return (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {picker}
          <Input.TextArea
            rows={4}
            value={String(current || '')}
            onChange={(e) => onChange(field.name, e.target.value)}
            placeholder={field.placeholder}
          />
        </Space>
      )
    case 'case_list':
      // case_list 由 NodeConfigForm 外层用 CaseListEditor 渲染，FieldControl 不直接处理
      return <Input.TextArea rows={4} value={String(current || '')} disabled />;
    case 'model_picker':
      // model_picker 由 NodeConfigForm 外层用 ModelPicker 渲染，FieldControl 不直接处理
      return <Input value={String(current || '')} disabled />;
    case 'key_value_list':
      // key_value_list 由 NodeConfigForm 外层用 KeyValueListEditor 渲染，FieldControl 不直接处理
      return <Input.TextArea rows={3} value={String(current || '')} disabled />;
    case 'text':
    default: {
      const isUrl = field.name === 'url';
      const isDatasetId = field.name === 'datasetId';
      if (isDatasetId) {
        return (
          <Select
            value={String(current || '') || undefined}
            onChange={(v) => onChange(field.name, v)}
            placeholder="选择知识库"
            style={{ width: '100%' }}
            options={(datasetOptions || []).map((d) => ({ value: d.id, label: d.title }))}
            notFoundContent="暂无知识库文档"
          />
        );
      }
      return (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <RefChipInput
            value={String(current || '')}
            onChange={(v) => onChange(field.name, v)}
            placeholder={field.placeholder}
            picker={picker}
            highlightPathParams={isUrl}
          />
          {isUrl && (
            <div style={{ fontSize: 11, color: '#9ca3af' }}>
              支持变量参数：https://api.example.com/users/<span style={{ color: CANVAS_TOKENS.accent }}>{'{{node.output.id}}'}</span>
            </div>
          )}
        </Space>
      );
    }
  }
}

// ========== IF case 可视化编辑器（T7） ==========
interface CaseItem {
  case_id: string;
  left: string;
  operator: string;
  right: string;
}

const CASE_OPERATORS: Array<{ value: string; label: string }> = [
  { value: 'eq', label: '等于 ==' },
  { value: 'ne', label: '不等于 !=' },
  { value: 'gt', label: '大于 >' },
  { value: 'gte', label: '大于等于 >=' },
  { value: 'lt', label: '小于 <' },
  { value: 'lte', label: '小于等于 <=' },
  { value: 'contains', label: '包含' },
  { value: 'not_contains', label: '不包含' },
  { value: 'is_empty', label: '为空' },
  { value: 'is_not_empty', label: '不为空' },
];

function parseCasesValue(raw: any): CaseItem[] {
  if (Array.isArray(raw)) {
    return raw.map((c, idx) => ({
      case_id: String(c?.case_id || c?.id || `case_${idx + 1}`),
      left: String(c?.left ?? ''),
      operator: String(c?.operator || 'eq'),
      right: String(c?.right ?? ''),
    }));
  }
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parseCasesValue(parsed);
    } catch {
      // ignore
    }
  }
  return [];
}

function CaseListEditor({
  value,
  onChange,
  nodes,
  currentNodeId,
  keyToMeta,
}: {
  value: any;
  onChange: (next: CaseItem[]) => void;
  nodes: GraphNodeSummary[];
  currentNodeId: string | null;
  keyToMeta: Record<string, NodeMeta>;
}) {
  const cases = useMemo(() => parseCasesValue(value), [value]);
  const leftValueOptions = useMemo(
    () => buildLeftValueOptions(nodes, currentNodeId, keyToMeta),
    [nodes, currentNodeId, keyToMeta],
  );

  const updateCase = (idx: number, patch: Partial<CaseItem>) => {
    const next = cases.map((c, i) => (i === idx ? { ...c, ...patch } : c));
    onChange(next);
  };

  const removeCase = (idx: number) => {
    onChange(cases.filter((_, i) => i !== idx));
  };

  const addCase = () => {
    const nextId = `case_${cases.length + 1}`;
    onChange([...cases, { case_id: nextId, left: '', operator: 'eq', right: '' }]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {cases.length === 0 && (
        <div style={{ fontSize: 12, color: '#999' }}>暂无条件，点击下方按钮添加</div>
      )}
      {cases.map((c, idx) => (
        <div
          key={`${c.case_id}-${idx}`}
          style={{
            padding: 10,
            background: '#fff',
            borderRadius: 8,
            border: '1px solid #e5e7eb',
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280', marginBottom: 8 }}>
            {idx === 0 ? '如果' : '否则，如果'} {idx + 1}
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <AutoComplete
              size="small"
              style={{ width: 200 }}
              placeholder="选择或输入左值"
              value={c.left}
              options={leftValueOptions}
              onChange={(text) => updateCase(idx, { left: text })}
              onSelect={(value) => updateCase(idx, { left: value })}
              allowClear
            />
            <Select
              size="small"
              style={{ width: 110 }}
              value={c.operator}
              onChange={(v) => updateCase(idx, { operator: v })}
              options={CASE_OPERATORS}
            />
            {c.operator !== 'is_empty' && c.operator !== 'is_not_empty' && (
              <Input
                size="small"
                style={{ width: 140 }}
                placeholder="右值"
                value={c.right}
                onChange={(e) => updateCase(idx, { right: e.target.value })}
                suffix={
                  <RefPickerButton
                    nodes={nodes}
                    currentNodeId={currentNodeId}
                    keyToMeta={keyToMeta}
                    onPick={(ref) => updateCase(idx, { right: ref })}
                  />
                }
              />
            )}
            <Button
              size="small"
              type="text"
              danger
              onClick={() => removeCase(idx)}
              aria-label="删除条件"
            >
              删除
            </Button>
          </div>
        </div>
      ))}
      {/* 否则静态卡片（U-IF1） */}
      <div
        style={{
          padding: 10,
          background: '#f9fafb',
          borderRadius: 8,
          border: '1px dashed #d1d5db',
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 600, color: '#6b7280' }}>否则</div>
        <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 4 }}>
          以上条件均不满足时执行此分支
        </div>
      </div>
      <Button size="small" onClick={addCase} style={{ alignSelf: 'flex-start' }} type="dashed">
        + 添加条件
      </Button>
    </div>
  );
}

// ========== 模型选择器（T8） ==========
// 模型 provider 彩色 logo 圆点（对齐 Coze 模型选择器视觉）
const PROVIDER_COLORS: Record<string, string> = {
  doubao: '#0052D9',
  bytedance: '#0052D9',
  volcengine: '#0052D9',
  ark: '#0052D9',
  openai: '#10A37F',
  anthropic: '#D97757',
  claude: '#D97757',
  deepseek: '#4D6BFE',
  qwen: '#615CED',
  tongyi: '#615CED',
  zhipu: '#3B7DFF',
  glm: '#3B7DFF',
  moonshot: '#FF6B4A',
  kimi: '#FF6B4A',
};

function providerColor(provider: string): string {
  const key = (provider || '').toLowerCase().trim();
  for (const k of Object.keys(PROVIDER_COLORS)) {
    if (key.includes(k)) return PROVIDER_COLORS[k];
  }
  return '#6b7280';
}

function ModelLabel({ name, provider }: { name: string; provider: string }) {
  const color = providerColor(provider);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: color,
          display: 'inline-block',
          flexShrink: 0,
        }}
      />
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {name}
        <span style={{ color: '#9ca3af', marginLeft: 6, fontSize: 12 }}>
          {provider || 'default'}
        </span>
      </span>
    </span>
  );
}

function ModelPicker({
  value,
  onChange,
}: {
  value: any;
  onChange: (patch: Partial<NodeConfigValues>) => void;
}) {
  const [models, setModels] = useState<ModelCatalogItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listAvailableModels()
      .then((rows) => {
        if (!cancelled) setModels(rows);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedModel = models.find((m) => m.model_id === value);

  return (
    <Select
      style={{ width: '100%' }}
      placeholder={loading ? '加载模型中...' : '选择模型'}
      loading={loading}
      value={value ? String(value) : undefined}
      showSearch
      optionFilterProp="labelText"
      labelRender={
        selectedModel
          ? () => (
              <ModelLabel
                name={selectedModel.display_name || selectedModel.model_id}
                provider={selectedModel.provider_name}
              />
            )
          : undefined
      }
      options={models.map((m) => ({
        value: m.model_id,
        labelText: `${m.display_name || m.model_id} ${m.provider_name || ''}`,
        label: <ModelLabel name={m.display_name || m.model_id} provider={m.provider_name} />,
        capabilities: m.capabilities,
      }))}
      onChange={(modelId, option) => {
        const patch: Partial<NodeConfigValues> = { modleName: modelId };
        const caps = (option as { capabilities?: ModelCatalogItem['capabilities'] }).capabilities;
        if (caps?.default_temperature !== undefined) {
          patch.temperature = caps.default_temperature;
        }
        if (caps?.default_max_tokens !== undefined) {
          patch.maxTokens = caps.default_max_tokens;
        }
        onChange(patch);
      }}
      notFoundContent={loading ? '加载中...' : '暂无可用模型'}
    />
  );
}

// ========== 动态 key-value 列表编辑器（T9：HTTP headers/query/form） ==========
interface KeyValueItem {
  key: string;
  value: string;
}

function parseKvValue(raw: any): KeyValueItem[] {
  if (Array.isArray(raw)) {
    return raw
      .filter((r) => r && typeof r === 'object')
      .map((r) => ({ key: String(r.key ?? r.name ?? ''), value: String(r.value ?? '') }));
  }
  if (raw && typeof raw === 'object') {
    return Object.entries(raw as Record<string, any>).map(([k, v]) => ({ key: k, value: String(v ?? '') }));
  }
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parseKvValue(parsed);
      if (parsed && typeof parsed === 'object') return parseKvValue(parsed);
    } catch {
      // fall through
    }
  }
  return [];
}

function KeyValueListEditor({
  value,
  onChange,
  nodes,
  currentNodeId,
  keyToMeta,
}: {
  value: any;
  onChange: (next: KeyValueItem[]) => void;
  nodes: GraphNodeSummary[];
  currentNodeId: string | null;
  keyToMeta: Record<string, NodeMeta>;
}) {
  const items = useMemo(() => parseKvValue(value), [value]);

  const updateItem = (idx: number, patch: Partial<KeyValueItem>) => {
    onChange(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const removeItem = (idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    onChange([...items, { key: '', value: '' }]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.length === 0 && (
        <div style={{ fontSize: 12, color: '#999' }}>暂无键值对，点击下方按钮添加</div>
      )}
      {items.map((it, idx) => (
        <div
          key={idx}
          style={{
            display: 'flex',
            gap: 6,
            alignItems: 'center',
            padding: 6,
            background: '#fafafa',
            borderRadius: 6,
            border: '1px solid #f0f0f0',
          }}
        >
          <Input
            size="small"
            style={{ width: 160 }}
            placeholder="Key"
            value={it.key}
            onChange={(e) => updateItem(idx, { key: e.target.value })}
          />
          <Input
            size="small"
            style={{ flex: 1 }}
            placeholder="Value {{node.output}}"
            value={it.value}
            onChange={(e) => updateItem(idx, { value: e.target.value })}
            suffix={
              <RefPickerButton
                nodes={nodes}
                currentNodeId={currentNodeId}
                keyToMeta={keyToMeta}
                onPick={(ref) => updateItem(idx, { value: it.value ? `${it.value} ${ref}` : ref })}
              />
            }
          />
          <Button
            size="small"
            type="text"
            danger
            onClick={() => removeItem(idx)}
            aria-label="删除"
          >
            删除
          </Button>
        </div>
      ))}
      <Button size="small" onClick={addItem} style={{ alignSelf: 'flex-start' }}>
        + 添加键值对
      </Button>
    </div>
  );
}

// ========== T15：运行 trace 面板条目 ==========
function TraceEntry({ entry }: { entry: { type: string; payload: Record<string, any> } }) {
  const { type, payload } = entry;
  const phase = payload.phase ? `[${payload.phase}${payload.reflect_round != null ? `#${payload.reflect_round}` : ''}${payload.tool_round != null ? `.${payload.tool_round}` : ''}]` : '';
  if (type === 'prompt_text') {
    if (Array.isArray(payload.messages)) {
      return (
        <div style={{ marginBottom: 6 }}>
          <Tag color="blue" style={{ fontSize: 10 }}>prompt {phase}</Tag>
          <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#f5f5f5', padding: 4, borderRadius: 4 }}>
            {payload.messages.map((m: any, i: number) =>
              `#${i} [${m.role}] ${typeof m.content === 'string' ? m.content : JSON.stringify(m.content)}\n`
            ).join('')}
          </pre>
        </div>
      );
    }
    return (
      <div style={{ marginBottom: 6 }}>
        <Tag color="geekblue" style={{ fontSize: 10 }}>assistant {phase}</Tag>
        <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#f5f5f5', padding: 4, borderRadius: 4 }}>
          {String(payload.content || '')}
          {Array.isArray(payload.tool_calls) && payload.tool_calls.length > 0 && (
            '\n→ tool_calls: ' + payload.tool_calls.map((tc: any) => tc.name).join(', ')
          )}
        </pre>
      </div>
    );
  }
  if (type === 'tool_call_start') {
    return (
      <div style={{ marginBottom: 6 }}>
        <Tag color="orange" style={{ fontSize: 10 }}>tool_call_start {phase}</Tag>
        <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#fff7e6', padding: 4, borderRadius: 4 }}>
          {payload.name}({String(payload.arguments || '')})
        </pre>
      </div>
    );
  }
  if (type === 'tool_call_end') {
    return (
      <div style={{ marginBottom: 6 }}>
        <Tag color="green" style={{ fontSize: 10 }}>tool_call_end {phase}</Tag>
        <pre style={{ margin: '4px 0 0', whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: '#f6ffed', padding: 4, borderRadius: 4 }}>
          {String(payload.observation || '')}
        </pre>
      </div>
    );
  }
  return null;
}

// ========== T14：节点 outputs 自定义编辑器 ==========
type OutputFieldItem = {
  name: string;
  type: string;
  description?: string;
};

const OUTPUT_TYPE_OPTIONS = [
  'string', 'number', 'boolean', 'object', 'array',
  'array[string]', 'array[number]', 'array[object]',
];

function parseOutputsValue(raw: any): OutputFieldItem[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((r) => r && typeof r === 'object')
    .map((r) => ({
      name: String(r.name ?? ''),
      type: String(r.type ?? 'string'),
      description: r.description ? String(r.description) : '',
    }));
}

function OutputsEditor({
  value,
  onChange,
}: {
  value: any;
  onChange: (next: OutputFieldItem[]) => void;
}) {
  const items = useMemo(() => parseOutputsValue(value), [value]);

  const updateItem = (idx: number, patch: Partial<OutputFieldItem>) => {
    onChange(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const removeItem = (idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    onChange([...items, { name: '', type: 'string', description: '' }]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.length === 0 && (
        <div style={{ fontSize: 12, color: '#999' }}>暂未定义输出字段，点击下方按钮添加</div>
      )}
      {items.map((it, idx) => (
        <div
          key={idx}
          style={{
            display: 'flex',
            gap: 6,
            alignItems: 'center',
            padding: 6,
            background: '#fafafa',
            borderRadius: 6,
            border: '1px solid #f0f0f0',
          }}
        >
          <Input
            size="small"
            style={{ width: 140 }}
            placeholder="字段名"
            value={it.name}
            onChange={(e) => updateItem(idx, { name: e.target.value })}
          />
          <Select
            size="small"
            style={{ width: 140 }}
            value={it.type}
            onChange={(v) => updateItem(idx, { type: v })}
            options={OUTPUT_TYPE_OPTIONS.map((t) => ({ value: t, label: t }))}
          />
          <Input
            size="small"
            style={{ flex: 1 }}
            placeholder="描述（可选）"
            value={it.description || ''}
            onChange={(e) => updateItem(idx, { description: e.target.value })}
          />
          <Button
            size="small"
            type="text"
            danger
            onClick={() => removeItem(idx)}
            aria-label="删除"
          >
            删除
          </Button>
        </div>
      ))}
      <Button size="small" onClick={addItem} style={{ alignSelf: 'flex-start' }}>
        + 添加输出字段
      </Button>
    </div>
  );
}

// V1/V2：右下角面板的 Tab 切换小标签
function TabSwitch({
  active, label, onClick,
}: { active: boolean; label: string; onClick: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        fontSize: 13, cursor: 'pointer', padding: '4px 8px',
        color: active ? '#4f46e5' : '#6b7280',
        borderBottom: active ? '2px solid #4f46e5' : '2px solid transparent',
        fontWeight: active ? 600 : 400,
      }}
    >
      {label}
    </span>
  );
}

// 配置分组折叠容器：折叠状态按节点类型持久化到 localStorage
function ConfigSectionBox({
  typeKey,
  title,
  defaultOpen,
  children,
}: {
  typeKey: string;
  title: string;
  defaultOpen: boolean;
  children: React.ReactNode;
}) {
  const storageKey = `boxia_cfg_sections_${typeKey}`;
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as Record<string, boolean>;
        if (typeof parsed[title] === 'boolean') return parsed[title];
      }
    } catch {
      // 本地缓存损坏时回落到默认展开状态
    }
    return defaultOpen;
  });

  const toggle = () => {
    setOpen((prev) => {
      const next = !prev;
      try {
        const raw = localStorage.getItem(storageKey);
        const parsed = raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
        parsed[title] = next;
        localStorage.setItem(storageKey, JSON.stringify(parsed));
      } catch {
        // 缓存写入失败不影响折叠交互
      }
      return next;
    });
  };

  return (
    <div style={{ marginTop: 4 }}>
      <div
        onClick={toggle}
        style={{
          display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
          padding: '4px 0',
          marginBottom: open ? 8 : 0,
          borderBottom: open ? '1px solid #f0f0f0' : 'none',
        }}
      >
        <span style={{
          fontSize: 9, color: '#9ca3af',
          display: 'inline-block',
          transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
          transition: 'transform 0.15s',
        }}>
          ▶
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>{title}</span>
      </div>
      {open && children}
    </div>
  );
}

function NodeConfigForm({
  nodeMeta,
  values,
  onChange,
  pickerNodes,
  currentNodeId,
  keyToMeta,
  outputs,
  onOutputsChange,
  datasetOptions,
  upstreamInputs,
  onAddNext,
}: {
  nodeMeta: NodeMeta;
  values: NodeConfigValues;
  onChange: (patch: Partial<NodeConfigValues>) => void;
  pickerNodes: GraphNodeSummary[];
  currentNodeId: string | null;
  keyToMeta: Record<string, NodeMeta>;
  outputs: OutputFieldItem[];
  onOutputsChange: (next: OutputFieldItem[]) => void;
  datasetOptions?: DatasetItem[];
  upstreamInputs?: UpstreamInputGroup[];
  onAddNext?: (typeKey: string) => void;
}) {
  const handleFieldChange = (name: string, value: any) => {
    onChange({ [name]: value });
  };

  const buildPicker = (fieldName: string): React.ReactNode => {
    // 只有文本类字段才挂变量引用选择器
    return (
      <RefPickerButton
        nodes={pickerNodes}
        currentNodeId={currentNodeId}
        keyToMeta={keyToMeta}
        onPick={(ref) => {
          const prev = String(values[fieldName] ?? '');
          const next = prev ? `${prev}${prev.endsWith(' ') ? '' : ' '}${ref}` : ref;
          handleFieldChange(fieldName, next);
        }}
      />
    );
  };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <div>
        <Typography.Text type="secondary">节点标题</Typography.Text>
        <Input
          value={values.title}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="节点显示名"
        />
      </div>

      <div>
        <Typography.Text type="secondary">输入（来自上游）</Typography.Text>
        <div style={{ marginTop: 6 }}>
          {(upstreamInputs || []).length === 0 ? (
            <div style={{
              padding: '8px 10px', background: '#f9fafb', borderRadius: 6,
              fontSize: 12, color: '#9ca3af',
            }}>
              无上游输入，请先连接上游节点
            </div>
          ) : (
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              {(upstreamInputs || []).map((group) => (
                <div key={group.nodeId} style={{
                  padding: '8px 10px', background: '#f9fafb', borderRadius: 6,
                }}>
                  <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>
                    {group.nodeTitle}
                  </div>
                  <Space size={[4, 4]} wrap>
                    {group.fields.map((f) => (
                      <Tag key={f.name} style={{ margin: 0, fontFamily: 'monospace', fontSize: 11 }}>
                        {`{{${group.nodeId}.output.${f.name}}}`}
                      </Tag>
                    ))}
                  </Space>
                </div>
              ))}
            </Space>
          )}
        </div>
      </div>

      {nodeMeta.config_fields.length === 0 && (
        <div style={{
          padding: '10px 12px', background: '#f9fafb', borderRadius: 6,
          fontSize: 12, color: '#6b7280', lineHeight: 1.6,
        }}>
          该节点无需额外配置：输入来自上游连线，输出字段见下方列表。
        </div>
      )}

      {groupConfigFields(nodeMeta.type_key, nodeMeta.config_fields).map((section) => (
        <ConfigSectionBox
          key={section.title}
          typeKey={nodeMeta.type_key}
          title={section.title}
          defaultOpen={section.title !== '高级'}
        >
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            {section.fields.map((field) => (
              <div key={field.name}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Typography.Text type="secondary">
                    {field.required && <span style={{ color: '#ff4d4f' }}>* </span>}
                    {field.label}
                  </Typography.Text>
                  {field.description && (
                    <Tooltip title={field.description}>
                      <span style={{ fontSize: 12, color: '#9ca3af', cursor: 'help' }}>ⓘ</span>
                    </Tooltip>
                  )}
                </div>
                {field.field_type === 'case_list' ? (
                  <CaseListEditor
                    value={values[field.name]}
                    onChange={(next) => handleFieldChange(field.name, next)}
                    nodes={pickerNodes}
                    currentNodeId={currentNodeId}
                    keyToMeta={keyToMeta}
                  />
                ) : field.field_type === 'model_picker' ? (
                  <ModelPicker
                    value={values[field.name]}
                    onChange={onChange}
                  />
                ) : field.field_type === 'key_value_list' ? (
                  <KeyValueListEditor
                    value={values[field.name]}
                    onChange={(next) => handleFieldChange(field.name, next)}
                    nodes={pickerNodes}
                    currentNodeId={currentNodeId}
                    keyToMeta={keyToMeta}
                  />
                ) : field.field_type === 'tool_list' ? (
                  <ToolListEditor
                    value={values[field.name]}
                    onChange={(next) => handleFieldChange(field.name, next)}
                  />
                ) : (
                  <FieldControl
                    field={field}
                    value={values[field.name]}
                    onChange={handleFieldChange}
                    picker={buildPicker(field.name)}
                    datasetOptions={datasetOptions}
                  />
                )}
              </div>
            ))}
          </Space>
        </ConfigSectionBox>
      ))}

      {hasOutputs(nodeMeta) && (
        <div>
          <Typography.Text type="secondary">输出字段（outputs）</Typography.Text>
          <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>
            自定义本节点产出的字段列表，保存后写入 node.data.outputs
          </div>
          <OutputsEditor value={outputs} onChange={onOutputsChange} />
        </div>
      )}

      {/* V10：下一步推荐 */}
      {onAddNext && getNextRecommendations(nodeMeta.type_key, keyToMeta).length > 0 && (
        <div style={{
          marginTop: 12, paddingTop: 12, borderTop: '1px solid #f0f0f0',
        }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8,
          }}>
            下一步
          </div>
          <Space direction="vertical" style={{ width: '100%' }} size={6}>
            {getNextRecommendations(nodeMeta.type_key, keyToMeta).map((rec) => {
              const meta = keyToMeta[rec.typeKey];
              return (
                <div
                  key={rec.typeKey}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
                    background: '#f9fafb',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = '#eef2ff'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = '#f9fafb'; }}
                  onClick={() => onAddNext(rec.typeKey)}
                >
                  <span style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: meta?.color || '#9ca3af',
                  }} />
                  <span style={{ flex: 1, fontSize: 13, color: '#374151' }}>{rec.label}</span>
                  <Button size="small" type="link">添加</Button>
                </div>
              );
            })}
          </Space>
        </div>
      )}
    </Space>
  );
}

// T9-07：对齐 Coze —— 空白处普通左键拖拽平移（Shift+拖拽由 selectBox 负责框选）。
// FlowGram 的选区插件在 canSelect 返回 false 时不会开始框选，也不会平移，需要自绘。
function setupCanvasPan(ctx: FlowContext): () => void {
  if (!ctx) return () => undefined;

  // 命中这些元素时不启动平移，避免抢走节点/端口/连线/浮层的既有交互
  const interactiveSelector = [
    '[data-node-id]',
    '[data-port-entity-id]',
    '.gedit-flow-activity-edge',
    '.boxia-minimap',
    '.ant-popover',
    '.ant-drawer',
    '.ant-dropdown',
    'button',
    'input',
    'textarea',
    'select',
    'a',
  ].join(',');

  // 空格按住时进入平移模式：指针落在节点上也平移，而不是拖动节点（N9-04）
  const overlaySelector = '.boxia-minimap, .ant-popover, .ant-dropdown, .ant-drawer, .ant-modal';
  const typingSelector = 'input, textarea, select, button, [contenteditable="true"]';

  let panning = false;
  let spaceDown = false;
  let startX = 0;
  let startY = 0;
  let originScrollX = 0;
  let originScrollY = 0;

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.code !== 'Space' || spaceDown) return;
    const target = e.target as HTMLElement | null;
    if (!target || target.closest(typingSelector)) return;
    if (!document.querySelector('.gedit-playground-container')) return;
    spaceDown = true;
    document.body.style.cursor = 'grab';
    // 阻止空格默认的页面滚动
    e.preventDefault();
  };

  const onKeyUp = (e: KeyboardEvent) => {
    if (e.code !== 'Space') return;
    spaceDown = false;
    if (!panning) document.body.style.cursor = '';
  };

  const onWindowBlur = () => {
    spaceDown = false;
    if (!panning) document.body.style.cursor = '';
  };

  // 用捕获阶段挂在 document 上：FlowGram 的拖拽层会 stopPropagation，冒泡阶段收不到
  const onPointerDown = (e: PointerEvent) => {
    if (e.button !== 0 || e.shiftKey) return;
    const target = e.target as HTMLElement | null;
    if (!target || !target.closest('.gedit-playground-container')) return;
    if (target.closest(overlaySelector)) return;
    if (spaceDown) {
      // 截断 FlowGram 的节点拖拽，本次指针序列只用于平移
      e.preventDefault();
      e.stopPropagation();
    } else if (target.closest(interactiveSelector)) {
      return;
    }
    panning = true;
    startX = e.clientX;
    startY = e.clientY;
    const origin = getScroll(ctx);
    originScrollX = origin.x;
    originScrollY = origin.y;
    document.body.style.cursor = 'grabbing';
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!panning) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    // scrollX/Y 是画布层的屏幕平移量，与鼠标位移 1:1
    setScroll(ctx, originScrollX + dx, originScrollY + dy);
  };

  const onPointerUp = () => {
    if (!panning) return;
    panning = false;
    document.body.style.cursor = spaceDown ? 'grab' : '';
  };

  document.addEventListener('pointerdown', onPointerDown, true);
  document.addEventListener('pointermove', onPointerMove, true);
  document.addEventListener('pointerup', onPointerUp, true);
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('keyup', onKeyUp, true);
  window.addEventListener('blur', onWindowBlur);
  return () => {
    panning = false;
    spaceDown = false;
    document.body.style.cursor = '';
    document.removeEventListener('pointerdown', onPointerDown, true);
    document.removeEventListener('pointermove', onPointerMove, true);
    document.removeEventListener('pointerup', onPointerUp, true);
    document.removeEventListener('keydown', onKeyDown, true);
    document.removeEventListener('keyup', onKeyUp, true);
    window.removeEventListener('blur', onWindowBlur);
  };
}

// ========== 页面组件 ==========
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export default function AppEditPage() {
  const { id } = useParams<{ id: string }>();
  const [initialData, setInitialData] = useState<WorkflowJSON | null>(null);
  const [nodeMetaReady, setNodeMetaReady] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeMeta, setSelectedNodeMeta] = useState<NodeMeta | null>(null);
  const [configValues, setConfigValues] = useState<NodeConfigValues>({});
  const [nodeOutputs, setNodeOutputs] = useState<OutputFieldItem[]>([]);
  const [upstreamInputs, setUpstreamInputs] = useState<UpstreamInputGroup[]>([]);
  const [running, setRunning] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishedVersion, setPublishedVersion] = useState<number | null>(null);
  const [runLogs, setRunLogs] = useState<Array<{ time: string; text: string; level?: 'info' | 'error' }>>([]);
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [startParams, setStartParams] = useState<Array<{ name: string; type?: string }>>([]);
  const [runInputs, setRunInputs] = useState<Record<string, any>>({});
  const [nodeDebugMap, setNodeDebugMap] = useState<Record<string, {
    status: RunNodeStatus;
    inputs?: any;
    outputs?: any;
    duration_ms?: number;
    error?: string;
    streamingText?: string;
    trace?: Array<{ type: string; payload: Record<string, any> }>;
  }>>({});
  const [validationIssues, setValidationIssues] = useState<GraphValidationIssue[]>([]);
  const [validating, setValidating] = useState(false);
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [versions, setVersions] = useState<GraphVersionItem[]>([]);
  const [approvalState, setApprovalState] = useState<{
    open: boolean;
    payload: ApprovalInterruptPayload | null;
    threadId: string;
    runId: string;
  }>({ open: false, payload: null, threadId: '', runId: '' });
  const [approvalComment, setApprovalComment] = useState('');
  const [approvalApprover, setApprovalApprover] = useState('');
  const [nodeMetas, setNodeMetas] = useState<NodeMeta[]>([]);
  const [nodeMetaCategories, setNodeMetaCategories] = useState<Record<string, NodeMeta[]>>({});
  const [pickerNodes, setPickerNodes] = useState<GraphNodeSummary[]>([]);
  const [canvasZoom, setCanvasZoom] = useState(1);
  // 画布可视区域（画布坐标系），用于小地图相机框与缩放百分比
  const [canvasViewport, setCanvasViewport] = useState<{ x: number; y: number; w: number; h: number; zoom: number } | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [deleteNodeOpen, setDeleteNodeOpen] = useState(false);
  // 卡片「⋯」重命名弹窗目标
  const [renameTarget, setRenameTarget] = useState<{ nodeId: string; value: string } | null>(null);
  // 多选集合（框选 / Shift 点选）与批量删除目标
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [deleteTargetIds, setDeleteTargetIds] = useState<string[]>([]);
  // 连线选中集合（点击连线时 FlowGram 会把 line 实体放进 selection）
  const selectedLineIdsRef = useRef<string[]>([]);
  // 配置抽屉开关与"选中节点"分离：关闭抽屉后仍保留选中态，供右键复制/删除使用
  const [configDrawerOpen, setConfigDrawerOpen] = useState(false);
  // 当前抽屉承载的节点，用于选择切换时判断是否需要关闭
  const drawerNodeIdRef = useRef<string | null>(null);
  const [variablesDrawerOpen, setVariablesDrawerOpen] = useState(false);
  const [addNodePopover, setAddNodePopover] = useState<{ x: number; y: number; fromNodeId?: string } | null>(null);
  const [datasetOptions, setDatasetOptions] = useState<DatasetItem[]>([]);
  // V4：左侧资源树折叠状态
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // 窄屏下手动展开后，本次会话不再被断点监听强制折叠
  const manualSidebarExpandRef = useRef(false);
  // V1/V2：右下角校验/日志合并面板
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelTab, setPanelTab] = useState<'validation' | 'logs'>('logs');
  usePortTooltips();
  const ctxRef = useRef<FreeLayoutPluginContext | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const nodeCounterRef = useRef<Record<string, number>>({});
  // 节点复制剪贴板：内存优先，localStorage 兜底跨刷新
  const nodeClipboardRef = useRef<{ typeKey: string; title?: string; config: Record<string, any>; outputs?: unknown[] } | null>(null);
  // 画布缩放/滚动订阅句柄，切换子图重挂载编辑器时先释放旧订阅
  const viewportDisposablesRef = useRef<Array<{ dispose?: () => void }>>([]);
  // FlowGram 选中集合同步句柄
  const selectionDisposableRef = useRef<{ dispose?: () => void } | null>(null);
  // 撤销/重做可用性（FlowGram history 插件开启后由 onApply 驱动）
  const [historyState, setHistoryState] = useState({ canUndo: false, canRedo: false });
  const historyDisposableRef = useRef<{ dispose?: () => void } | null>(null);
  // 空白拖拽平移的监听器释放句柄（编辑器重挂载时先解绑）
  const panCleanupRef = useRef<(() => void) | null>(null);

  // 同步画布缩放与可视区域：小地图相机框、底部工具栏缩放百分比都依赖它
  const syncCanvasViewport = useCallback(() => {
    const viewport = getViewport(ctxRef.current);
    if (!viewport) return;
    setCanvasZoom(viewport.zoom);
    setCanvasViewport(viewport);
  }, []);

  useEffect(() => () => {
    viewportDisposablesRef.current.forEach((d) => d.dispose?.());
    viewportDisposablesRef.current = [];
    selectionDisposableRef.current?.dispose?.();
    selectionDisposableRef.current = null;
    historyDisposableRef.current?.dispose?.();
    historyDisposableRef.current = null;
    panCleanupRef.current?.();
    panCleanupRef.current = null;
  }, []);

  // 窄屏自动折叠左侧栏（U-P4）
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1100px)');
    const apply = () => {
      if (mq.matches) {
        manualSidebarExpandRef.current = false;
        setSidebarCollapsed(true);
      } else if (!manualSidebarExpandRef.current) {
        setSidebarCollapsed(false);
      }
    };
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);

  // 拖线时高亮可落点的输入端口（FlowGram 仅在非绘制态做 hover，需自行标记）
  useEffect(() => {
    let dragging = false;
    let activePortEl: HTMLElement | null = null;
    const clearActive = () => {
      activePortEl?.classList.remove('boxia-port-drop-target');
      activePortEl = null;
    };
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target?.closest?.('.gedit-playground-container')) return;
      dragging = Boolean(target.closest('[data-port-entity-type="output"]'));
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!dragging) return;
      const ctx = ctxRef.current;
      const worldPos = getWorldPosFromMouseEvent(ctx, e);
      if (!worldPos) return;
      const port = getPortFromMousePos(ctx, worldPos);
      const nextEl = port?.portType === 'input'
        ? (document.querySelector(`[data-port-entity-id="${port.id}"]`) as HTMLElement | null)
        : null;
      if (nextEl !== activePortEl) {
        clearActive();
        activePortEl = nextEl;
        activePortEl?.classList.add('boxia-port-drop-target');
      }
    };
    const onPointerUp = () => {
      dragging = false;
      clearActive();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('pointermove', onPointerMove, true);
    window.addEventListener('pointerup', onPointerUp, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('pointermove', onPointerMove, true);
      window.removeEventListener('pointerup', onPointerUp, true);
      clearActive();
    };
  }, []);

  // ========== 子图导航（B6） ==========
  // rootGraphRef 持有完整嵌套 WorkflowJSON（每个子图节点的 data.subgraph）
  // subgraphStack 记录从 root 到当前编辑层的 node_id 路径；空数组 = 编辑 root
  // editorKey 强制 FreeLayoutEditor 重挂载（切换层级时 initialData 改变）
  const rootGraphRef = useRef<WorkflowJSON>(DEFAULT_GRAPH);
  // Coze IR 的 schema 版本来自后端独立字段，保存时原样透传
  const graphSchemaVersionRef = useRef(DEFAULT_SCHEMA_VERSION);
  const [subgraphStack, setSubgraphStack] = useState<string[]>([]);
  const [editorKey, setEditorKey] = useState(0);
  const [subgraphBreadcrumb, setSubgraphBreadcrumb] = useState<Array<{ id: string; title: string }>>([]);

  // 把当前 FreeLayoutEditor 的 JSON 回写到 rootGraphRef 对应层级
  const persistCurrentEditor = useCallback(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const json = toWorkflowJSON(ctx);
    const stack = subgraphStack;
    if (stack.length === 0) {
      rootGraphRef.current = json;
      return;
    }
    // 沿 stack 找到父节点，把 json 写入其 data.subgraph
    let cursor: WorkflowJSON = rootGraphRef.current;
    for (let i = 0; i < stack.length; i++) {
      const nodeId = stack[i];
      const node = (cursor.nodes || []).find((n) => n.id === nodeId) as unknown as {
        data?: Record<string, unknown>;
      } | undefined;
      if (!node) return;
      if (i === stack.length - 1) {
        node.data = { ...(node.data || {}), subgraph: json };
      } else {
        const next = (node.data?.subgraph || DEFAULT_GRAPH) as WorkflowJSON;
        cursor = next;
      }
    }
  }, [subgraphStack]);

  // 按 stack 从 rootGraphRef 取出当前要编辑的 WorkflowJSON
  const resolveEditorData = useCallback((stack: string[]): WorkflowJSON => {
    let cursor: WorkflowJSON = rootGraphRef.current;
    for (const nodeId of stack) {
      const node = (cursor.nodes || []).find((n) => n.id === nodeId) as unknown as {
        data?: Record<string, unknown>;
      } | undefined;
      if (!node) return DEFAULT_GRAPH;
      cursor = ((node.data?.subgraph as WorkflowJSON) || DEFAULT_GRAPH);
    }
    return cursor;
  }, []);

  const enterSubgraph = useCallback((nodeId: string, nodeTitle: string) => {
    persistCurrentEditor();
    setSubgraphStack((prev) => {
      const nextStack = [...prev, nodeId];
      setSubgraphBreadcrumb((bc) => [...bc, { id: nodeId, title: nodeTitle || nodeId }]);
      setInitialData(resolveEditorData(nextStack));
      setEditorKey((k) => k + 1);
      return nextStack;
    });
    setSelectedNodeId(null);
    setConfigDrawerOpen(false);
  }, [persistCurrentEditor, resolveEditorData]);

  const exitSubgraph = useCallback((levels: number) => {
    persistCurrentEditor();
    setSubgraphStack((prev) => {
      const nextStack = prev.slice(0, Math.max(0, prev.length - levels));
      setSubgraphBreadcrumb((bc) => bc.slice(0, Math.max(0, bc.length - levels)));
      setInitialData(resolveEditorData(nextStack));
      setEditorKey((k) => k + 1);
      return nextStack;
    });
    setSelectedNodeId(null);
    setConfigDrawerOpen(false);
  }, [persistCurrentEditor, resolveEditorData]);

  // ========== 拉取节点元数据 ==========
  useEffect(() => {
    (async () => {
      try {
        const resp = await getNodeMeta();
        setNodeMetas(resp.items);
        setNodeMetaCategories(resp.categories);
      } catch {
        message.error('加载节点库失败');
      } finally {
        // 节点类型注册表是画布渲染的前置条件：为空时渲染节点会得到 0 尺寸
        setNodeMetaReady(true);
      }
    })();
    listDatasets()
      .then((rows) => setDatasetOptions(rows))
      .catch(() => setDatasetOptions([]));
  }, []);

  // ========== 构建 cozeType ↔ type_key 映射 ==========
  const cozeTypeToKey = useMemo(() => {
    const map: Record<string, string> = {};
    nodeMetas.forEach((m) => { map[m.type_code] = m.type_key; });
    return map;
  }, [nodeMetas]);

  const keyToCozeType = useMemo(() => {
    const map: Record<string, string> = {};
    nodeMetas.forEach((m) => { map[m.type_key] = m.type_code; });
    return map;
  }, [nodeMetas]);

  const keyToMeta = useMemo(() => {
    const map: Record<string, NodeMeta> = {};
    nodeMetas.forEach((m) => { map[m.type_key] = m; });
    return map;
  }, [nodeMetas]);

  // N9-06：导出当前工作流为 Coze IR JSON
  const handleExportJson = useCallback(() => {
    const graph = toWorkflowJSON(ctxRef.current);
    if (!graph || !Array.isArray(graph.nodes) || graph.nodes.length === 0) {
      message.info('画布为空，无内容可导出');
      return;
    }
    const ir = toCozeIR(graph, keyToCozeType, graphSchemaVersionRef.current);
    const blob = new Blob([JSON.stringify(ir, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${id || 'workflow'}.json`;
    link.click();
    URL.revokeObjectURL(url);
    message.success('已导出工作流 JSON');
  }, [keyToCozeType, id]);
  // onLoad 闭包会长期驻留，通过 ref 读取最新的节点元数据
  const keyToMetaRef = useRef<Record<string, NodeMeta>>(keyToMeta);
  keyToMetaRef.current = keyToMeta;

  // ========== 节点注册表 ==========
  const nodeRegistries: WorkflowNodeRegistry[] = useMemo(() => {
    return nodeMetas.map((meta) => {
      // 按 outputs 数量动态计算高度，避免端口圆点覆盖卡片拖拽区域
      const baseHeight = 52;
      const outputPortHeight = meta.outputs.length > 1 ? (meta.outputs.length - 1) * 20 : 0;
      const height = meta.type_key === 'comment' || meta.type_key === 'note'
        ? 100
        : baseHeight + outputPortHeight;
      return {
        type: meta.type_key,
        meta: {
          defaultPorts: [
            ...meta.inputs.map((p) => ({ portID: p.name, type: 'input' as const })),
            ...meta.outputs.map((p) => ({ portID: p.name, type: 'output' as const })),
          ],
          size: { width: 220, height },
          renderKey: meta.type_key,
        },
      };
    });
  }, [nodeMetas]);

  // ========== 加载图 ==========
  useEffect(() => {
    // 必须等节点元数据就绪：cozeTypeToKey 为空时 fromCozeIR 无法把数字类型
    // 转回注册表 key，节点会因找不到渲染器而变成 0 尺寸空白节点。
    if (!id || !nodeMetaReady) return;
    let cancelled = false;
    (async () => {
      try {
        try {
          const resp = await getAppGraph(id);
          if (cancelled) return;
          setPublishedVersion(resp.published_graph_version ?? null);
          graphSchemaVersionRef.current = resp.graph_schema_version ?? readSchemaVersion(resp.graph);
          const graph = fromCozeIR(resp.graph, cozeTypeToKey);
          rootGraphRef.current = graph;
          setSubgraphStack([]);
          setSubgraphBreadcrumb([]);
          setInitialData(graph);
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            if (!cancelled) {
              rootGraphRef.current = DEFAULT_GRAPH;
              setSubgraphStack([]);
              setSubgraphBreadcrumb([]);
              setInitialData(DEFAULT_GRAPH);
            }
          } else {
            throw err;
          }
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : '加载画布失败');
        }
      }
    })();
    return () => { cancelled = true; };
  }, [id, nodeMetaReady, cozeTypeToKey]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    };
  }, []);

  // ========== 保存 ==========
  const collectIssuesForNodes = useCallback((issues: GraphValidationIssue[]) => {
    // 清除旧红框
    document.querySelectorAll('.boxia-node-invalid').forEach((el) => {
      el.classList.remove('boxia-node-invalid');
    });
    issues.forEach((issue) => {
      if (!issue.node_id) return;
      const el = document.getElementById(issue.node_id);
      if (!el) return;
      const inner = el.querySelector<HTMLElement>('div[draggable="true"] > div');
      if (inner) inner.classList.add('boxia-node-invalid');
    });
  }, []);

  // 收集当前完整嵌套图（含子图），用于校验/保存
  const collectFullGraph = useCallback((): WorkflowJSON => {
    persistCurrentEditor();
    return rootGraphRef.current;
  }, [persistCurrentEditor]);

  const doValidate = useCallback(async (): Promise<GraphValidationIssue[]> => {
    const ctx = ctxRef.current;
    if (!ctx) return [];
    setValidating(true);
    try {
      const flowgram = collectFullGraph();
      const cozeIR = toCozeIR(flowgram, keyToCozeType, graphSchemaVersionRef.current);
      const result = await validateGraph(cozeIR as never);
      setValidationIssues(result.issues);
      collectIssuesForNodes(result.issues);
      // 自动保存触发的校验不再弹出右下角面板：面板会遮挡画布，导致新节点无法拖拽。
      // 需要查看问题时点击顶部状态栏的“校验”入口。
      return result.issues;
    } catch {
      message.error('校验请求失败');
      return [];
    } finally {
      setValidating(false);
    }
  }, [keyToCozeType, collectIssuesForNodes, collectFullGraph]);

  const scheduleSave = useCallback(() => {
    if (!ctxRef.current || !id) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    setSaveStatus('saving');
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        // 校验只用于红框/问题提示，不阻塞草稿保存：
        // 新增未连线节点、必填项未填都是编辑中间态，应允许随时落盘。
        await doValidate();
        const flowgram = collectFullGraph();
        const cozeIR = toCozeIR(flowgram, keyToCozeType, graphSchemaVersionRef.current);
        await saveAppGraph(id, cozeIR as never);
        setSaveStatus('saved');
        setLastSavedAt(new Date());
      } catch {
        setSaveStatus('error');
      }
    }, 800);
  }, [id, keyToCozeType, doValidate, collectFullGraph]);

  const handlePublish = useCallback(async () => {
    if (!id) return;
    // 发布是运行态闸门：先做严格校验，有 error 不发布
    const issues = await doValidate();
    const errors = issues.filter((i) => i.severity === 'error');
    if (errors.length > 0) {
      setPanelTab('validation');
      setPanelOpen(true);
      message.error(`有 ${errors.length} 个校验问题，请先修复再发布`);
      return;
    }
    // 发布前先同步保存一次 draft，确保快照是最新的
    await new Promise<void>((resolve) => {
      scheduleSave();
      setTimeout(resolve, 1000);
    });
    setPublishing(true);
    try {
      const result = await publishGraph(id);
      if (result.published_version != null) setPublishedVersion(result.published_version);
      message.success(`发布成功，当前 live 版本 v${result.published_version ?? '?'}`);
    } catch (e) {
      message.error(`发布失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPublishing(false);
    }
  }, [id, doValidate, scheduleSave]);

  // ========== 添加节点 ==========
  const addNode = useCallback((typeKey: string, options?: { fromNodeId?: string; screenX?: number; screenY?: number }) => {
    const ctx = ctxRef.current;
    if (!ctx) return null;
    const meta = keyToMeta[typeKey];
    if (!meta) return null;
    nodeCounterRef.current[typeKey] = (nodeCounterRef.current[typeKey] ?? 0) + 1;
    const nodeId = `${typeKey}-${Date.now().toString(36)}-${nodeCounterRef.current[typeKey]}`;

    // 从当前文档 JSON 读取节点位置（toJSON 的 meta.position 即真实 TransformData 位置）
    const docJson = toWorkflowJSON(ctx);
    const allNodes = (docJson.nodes || []) as Array<{ id: string; meta?: { position?: { x: number; y: number } } }>;

    let posX = 400;
    let posY = 300;

    // 找到 START 节点作为锚点：所有"非 fromNodeId"的新增都默认贴在 START 右侧，
    // 避免新节点出现在用户视口外、看起来像没创建出来
    const startNode = allNodes.find((n) => String(n.type || n.id.split('-')[0]) === 'start' && n.meta?.position);

    if (options?.fromNodeId) {
      const fromNode = allNodes.find((n) => n.id === options.fromNodeId);
      if (fromNode?.meta?.position) {
        posX = fromNode.meta.position.x + 260;
        posY = fromNode.meta.position.y;
      }
    } else if (startNode?.meta?.position) {
      posX = startNode.meta.position.x + 260;
      posY = startNode.meta.position.y;
    } else {
      const count = allNodes.length;
      posX = 300 + (count % 5) * 60;
      posY = 200 + (count % 4) * 70;
    }

    // 位置避让：与已有节点重叠时逐格向下挪，避免新节点盖住老节点导致看不见
    const NODE_BOX_WIDTH = 240;
    const NODE_BOX_HEIGHT = 80;
    const occupied = allNodes
      .map((n) => n.meta?.position)
      .filter((p): p is { x: number; y: number } => !!p);
    const collides = (x: number, y: number) =>
      occupied.some((p) => Math.abs(p.x - x) < NODE_BOX_WIDTH && Math.abs(p.y - y) < NODE_BOX_HEIGHT);
    let attempts = 0;
    while (collides(posX, posY) && attempts < 30) {
      posY += NODE_BOX_HEIGHT + 16;
      attempts += 1;
    }

    // 必须走 createWorkflowNodeByType：裸 addNode 不会初始化 TransformData，
    // 节点会渲染在 (0,0) 且无法拖拽
    createNodeByType(ctx, meta.type_key, { x: posX, y: posY }, {
      id: nodeId,
      data: { title: meta.title, config: {} },
    });

    // 新节点添加后自动适应视图，确保用户能看到新节点（WorkflowDocument.fitView）
    setTimeout(() => { void fitView(ctx, true); }, 100);

    // V9/V10：自动从 source 节点第一个 output 端口连线到新节点第一个 input 端口
    if (options?.fromNodeId) {
      const fromNodeId = options.fromNodeId;
      const fromNode = getNode(ctx, fromNodeId);
      if (fromNode) {
        const fromMeta = keyToMeta[getNodeTypeKey(fromNode)];
        const fromPortId = fromMeta?.outputs?.[0]?.name;
        const toPortId = meta.inputs?.[0]?.name;
        if (fromPortId) {
          createLine(ctx, {
            from: fromNodeId,
            fromPort: fromPortId,
            to: nodeId,
            toPort: toPortId || undefined,
          });
        }
      }
    }
    return nodeId;
  }, [keyToMeta]);

  // ========== 节点复制 / 粘贴（右键菜单） ==========
  const NODE_CLIPBOARD_KEY = 'boxia_node_clipboard';

  const copyNodeById = useCallback((nodeId: string | null) => {
    if (!ctxRef.current || !nodeId) {
      message.info('请先选中一个节点');
      return;
    }
    const node = getNode(ctxRef.current, nodeId);
    if (!node) {
      message.error('未找到选中节点');
      return;
    }
    const typeKey = getNodeTypeKey(node);
    const meta = keyToMeta[typeKey];
    if (!canCopy(meta, typeKey)) {
      message.error('该节点不支持复制');
      return;
    }
    const data = getNodeExtInfo(node);
    const payload = {
      typeKey,
      title: data.title ? String(data.title) : meta?.title || typeKey,
      config: (data.config || {}) as Record<string, any>,
      outputs: Array.isArray(data.outputs) ? data.outputs : [],
    };
    nodeClipboardRef.current = payload;
    try {
      localStorage.setItem(NODE_CLIPBOARD_KEY, JSON.stringify(payload));
    } catch {
      // localStorage 写满时仅用内存剪贴板
    }
    message.success(`已复制「${payload.title}」`);
  }, [keyToMeta]);

  const copyNode = useCallback(() => copyNodeById(selectedNodeId), [copyNodeById, selectedNodeId]);

  const pasteNode = useCallback(() => {
    let payload = nodeClipboardRef.current;
    if (!payload) {
      try {
        const raw = localStorage.getItem(NODE_CLIPBOARD_KEY);
        if (raw) payload = JSON.parse(raw);
      } catch {
        payload = null;
      }
    }
    if (!payload || !payload.typeKey) {
      message.info('剪贴板为空，请先复制一个节点');
      return;
    }
    const newId = addNode(payload.typeKey);
    if (!newId) {
      message.error('粘贴失败：未知节点类型');
      return;
    }
    const node = getNode(ctxRef.current, newId);
    if (node) {
      updateNodeExtInfo(node, {
        title: payload.title ? `${payload.title} 副本` : keyToMeta[payload.typeKey]?.title,
        config: JSON.parse(JSON.stringify(payload.config || {})),
        outputs: JSON.parse(JSON.stringify(payload.outputs || [])),
      });
    }
    message.success('节点已粘贴');
    // 等新节点数据落盘后再触发保存
    setTimeout(() => scheduleSave(), 100);
  }, [addNode, keyToMeta, scheduleSave]);

  // ========== 卡片「⋯」菜单（N9-07） ==========
  const handleCardRename = useCallback((node: WorkflowNodeEntity) => {
    const typeKey = getNodeTypeKey(node);
    const data = getNodeExtInfo(node);
    setRenameTarget({
      nodeId: node.id,
      value: String(data.title || keyToMeta[typeKey]?.title || typeKey),
    });
  }, [keyToMeta]);

  const confirmCardRename = useCallback(() => {
    if (!renameTarget) return;
    const title = renameTarget.value.trim();
    if (!title) {
      message.warning('节点名称不能为空');
      return;
    }
    const node = getNode(ctxRef.current, renameTarget.nodeId);
    if (!node) {
      message.error('未找到节点');
      setRenameTarget(null);
      return;
    }
    updateNodeExtInfo(node, { title });
    scheduleSave();
    setRenameTarget(null);
  }, [renameTarget, scheduleSave]);

  const handleCardCopy = useCallback((node: WorkflowNodeEntity) => {
    copyNodeById(node.id);
  }, [copyNodeById]);

  const handleCardDelete = useCallback((node: WorkflowNodeEntity) => {
    const typeKey = getNodeTypeKey(node);
    if (!canDelete(keyToMeta[typeKey], typeKey)) {
      message.warning('该节点不允许删除');
      return;
    }
    setDeleteTargetIds([node.id]);
    setDeleteNodeOpen(true);
  }, [keyToMeta]);

  const nodeCardActions = useMemo<NodeCardActions>(() => ({
    onRename: handleCardRename,
    onCopy: handleCardCopy,
    onDelete: handleCardDelete,
  }), [handleCardRename, handleCardCopy, handleCardDelete]);

  // ========== 双击节点打开配置 ==========
  const refreshPickerNodes = useCallback(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const json = toWorkflowJSON(ctx);
    const nodes: GraphNodeSummary[] = (json.nodes || []).map((n) => {
      const data = (n.data || {}) as { title?: string; config?: Record<string, any> };
      const meta = (n.meta || {}) as { position?: { x: number; y: number } };
      const typeKey = String(n.type || '');
      return {
        id: String(n.id),
        typeKey,
        title: data?.title || typeKey,
        config: data?.config || {},
        position: meta.position,
      };
    });
    setPickerNodes(nodes);
  }, []);

  const handleNodeDoubleClick = useCallback((node: WorkflowNodeEntity) => {
    const nodeTypeKey = getNodeTypeKey(node);
    const nodeData = getNodeExtInfo(node) as {
      title?: string; config?: NodeConfigValues; outputs?: unknown[]; subgraph?: WorkflowJSON;
    };

    // 子图节点：双击直接进入子图编辑
    if (hasSubgraph(keyToMetaRef.current[nodeTypeKey], nodeTypeKey)) {
      // 首次进入时如果还没有 subgraph，自动初始化一个空 START 节点
      const existing = (nodeData.subgraph as WorkflowJSON | undefined);
      if (!existing || !Array.isArray(existing.nodes) || existing.nodes.length === 0) {
        const subId = `${node.id}-inner-${Date.now().toString(36)}`;
        const initSubgraph: WorkflowJSON = {
          nodes: [
            {
              id: subId,
              type: 'start',
              meta: { position: { x: 200, y: 200 } },
              data: { title: '入口', config: {} },
            } as WorkflowJSON['nodes'][number],
          ],
          edges: [],
        };
        // 同步回写到节点 extInfo（FlowGram 的节点数据载体）
        updateNodeExtInfo(node, { subgraph: initSubgraph });
      }
      enterSubgraph(node.id, nodeData.title || nodeTypeKey);
      return;
    }

    setSelectedNodeId(node.id);
    drawerNodeIdRef.current = node.id;
    setConfigDrawerOpen(true);
    const meta = keyToMeta[nodeTypeKey];
    if (meta) {
      setSelectedNodeMeta(meta);
    }
    setConfigValues({
      title: nodeData.title,
      ...(nodeData.config || {}),
    });
    setNodeOutputs(parseOutputsValue(nodeData.outputs));

    // 抽屉「输入」区：按入边反查上游可引用字段
    const json = toWorkflowJSON(ctxRef.current);
    const edges = ((json?.edges || []) as unknown as Array<{ source?: string; target?: string }>);
    const groups: UpstreamInputGroup[] = [];
    for (const edge of edges) {
      if (String(edge.target) !== node.id) continue;
      const srcId = String(edge.source || '');
      const src = (json?.nodes || []).find((n) => String(n.id) === srcId);
      if (!src) continue;
      const srcData = (src.data || {}) as Record<string, any>;
      const srcTypeKey = String(src.type || srcId.split('-')[0]);
      const srcMeta = keyToMeta[srcTypeKey];
      const fields = srcTypeKey === 'start'
        ? (Array.isArray(srcData.config?.inputs)
            ? srcData.config.inputs.map((inp: any) => ({ name: String(inp?.name || ''), label: '启动参数' }))
            : [])
        : (Array.isArray(srcData.outputs) && srcData.outputs.length > 0
            ? srcData.outputs.map((o: any) => ({ name: String(o?.name || ''), label: String(o?.description || '') }))
            : (srcMeta?.outputs || []).map((p) => ({ name: p.name, label: p.label || '' })));
      const cleaned = fields.filter((f: { name: string }) => f.name);
      if (cleaned.length === 0) continue;
      groups.push({
        nodeId: srcId,
        nodeTitle: String(srcData.title || srcMeta?.title || srcId),
        fields: cleaned,
      });
    }
    setUpstreamInputs(groups);
    refreshPickerNodes();
  }, [keyToMeta, refreshPickerNodes, enterSubgraph]);

  // ========== 删除节点（U-S3） ==========
  const confirmDeleteNode = useCallback(() => {
    const ctx = ctxRef.current;
    const ids = deleteTargetIds.length > 0
      ? deleteTargetIds
      : (selectedNodeId ? [selectedNodeId] : []);
    if (!ctx || ids.length === 0) {
      setDeleteNodeOpen(false);
      return;
    }
    const resolveTypeKey = (nodeId: string): string => getNodeTypeKey(getNode(ctx, nodeId));
    const deletable = ids.filter((nodeId) => {
      const typeKey = resolveTypeKey(nodeId);
      return canDelete(keyToMeta[typeKey], typeKey);
    });
    if (deletable.length === 0) {
      message.warning('所选节点不允许删除');
      setDeleteNodeOpen(false);
      return;
    }
    let removed = 0;
    for (const nodeId of deletable) {
      if (removeNode(ctx, nodeId)) removed += 1;
    }
    // 清空 FlowGram 选中集合，避免残留已删除节点导致后续点击不再触发选中同步
    clearSelection(ctx);
    const skipped = ids.length - deletable.length;
    if (removed > 0) {
      const base = removed > 1 ? `已删除 ${removed} 个节点` : '节点已删除';
      message.success(skipped > 0 ? `${base}，不可删除的节点已跳过` : base);
    } else {
      message.error('删除节点失败');
    }
    setSelectedNodeId(null);
    setSelectedNodeIds([]);
    setDeleteTargetIds([]);
    setConfigDrawerOpen(false);
    drawerNodeIdRef.current = null;
    setDeleteNodeOpen(false);
    scheduleSave();
  }, [deleteTargetIds, selectedNodeId, keyToMeta, scheduleSave]);

  // V9：节点右上角 + 按钮 → 在节点下方弹出 AddNodePopover（自动连线到当前节点）
  const handleAddNextToNode = useCallback((node: WorkflowNodeEntity) => {
    const el = document.getElementById(node.id);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setAddNodePopover({
      x: rect.left + rect.width / 2 - 140,
      y: rect.bottom + 8,
      fromNodeId: node.id,
    });
  }, []);

  const renderNodes = useMemo(() => {
    return Object.fromEntries(
      nodeMetas.map((meta) => [
        meta.type_key,
        makeNodeRenderer(meta, ctxRef, handleNodeDoubleClick, handleAddNextToNode, nodeCardActions) as unknown as React.ComponentType<any>,
      ]),
    ) as Record<string, React.ComponentType<any>>;
  }, [nodeMetas, handleNodeDoubleClick, handleAddNextToNode, nodeCardActions]);

  // ========== 抽屉配置变更 ==========
  const handleConfigChange = useCallback((patch: Partial<NodeConfigValues>) => {
    setConfigValues((prev) => {
      const next = { ...prev, ...patch };
      const ctx = ctxRef.current;
      if (ctx && selectedNodeId) {
        const node = getNode(ctx, selectedNodeId);
        if (node) {
          // title 单独存放，避免混入 config 后被写进后端 inputs
          const { title, ...configOnly } = next;
          updateNodeExtInfo(node, { title, config: configOnly });
        }
      }
      return next;
    });
  }, [selectedNodeId]);

  const handleOutputsChange = useCallback((next: OutputFieldItem[]) => {
    setNodeOutputs(next);
    const ctx = ctxRef.current;
    if (ctx && selectedNodeId) {
      const node = getNode(ctx, selectedNodeId);
      if (node) {
        updateNodeExtInfo(node, {
          outputs: next.map((it) => ({
            name: it.name,
            type: it.type,
            ...(it.description ? { description: it.description } : {}),
          })),
        });
      }
    }
  }, [selectedNodeId]);

  // ========== 连线校验：只做基础校验，方向由 FlowGram 拖线机制保证 ==========
  const canAddLine = useCallback((
    _ctx: FreeLayoutPluginContext,
    fromPort: WorkflowPortEntity,
    toPort: WorkflowPortEntity,
    _lines: WorkflowLinesManager,
    silent?: boolean,
  ) => {
    // 不做端口方向校验（FlowGram 拖线本身只能从 output 发起）。
    // 端口 id 仅为端口名（如 "default"/"true"/"false"），不是全局唯一，
    // 因此不能用 fromPort.id === toPort.id 判重（START.default → IF.default 会被误拒）。
    // 只防止同节点自连。
    if (!fromPort || !toPort) return false;
    const fromNodeId = (fromPort as unknown as { node?: { id?: string } }).node?.id;
    const toNodeId = (toPort as unknown as { node?: { id?: string } }).node?.id;
    if (fromNodeId && fromNodeId === toNodeId) return false;
    return true;
  }, []);

  // ========== 运行时高亮（直接操作 DOM，绕过 FlowGram 响应式） ==========
  const NODE_SHADOW: Record<RunNodeStatus, string> = {
    running: '0 0 0 3px rgba(139,92,246,0.35)',
    success: '0 0 0 3px rgba(16,185,129,0.35)',
    error: '0 0 0 3px rgba(239,68,68,0.35)',
  };

  const setNodeRunStatus = useCallback((nodeId: string, status: RunNodeStatus | undefined) => {
    const el = document.getElementById(nodeId);
    if (!el) return;
    const inner = el.querySelector<HTMLElement>('div[draggable="true"] > div');
    if (!inner) return;
    if (status === undefined) {
      inner.style.boxShadow = '';
      inner.classList.remove('boxia-node-running');
    } else {
      inner.style.boxShadow = NODE_SHADOW[status];
      if (status === 'running') inner.classList.add('boxia-node-running');
      else inner.classList.remove('boxia-node-running');
    }
  }, []);

  const clearAllRunStatus = useCallback(() => {
    document.querySelectorAll('.gedit-flow-activity-node').forEach((el) => {
      const inner = el.querySelector<HTMLElement>('div[draggable="true"] > div');
      if (!inner) return;
      inner.style.boxShadow = '';
      inner.classList.remove('boxia-node-running');
    });
  }, []);

  // ========== 试运行 ==========
  const extractStartParams = useCallback((): Array<{ name: string; type?: string }> => {
    const ctx = ctxRef.current;
    if (!ctx) return [];
    const flowgram = toWorkflowJSON(ctx);
    const startNode = (flowgram.nodes || []).find((n) => n.type === 'start');
    if (!startNode) return [];
    const data = (startNode.data || {}) as { config?: { inputs?: Array<{ name: string; type?: string }> } };
    return Array.isArray(data?.config?.inputs) ? data.config.inputs : [];
  }, []);

  // 共用的 SSE 事件处理器（初次 + resume 复用）
  const handleRunEvent = useCallback((
    event: { event: string; data: Record<string, any> },
    appendLog: (text: string, level?: 'info' | 'error') => void,
  ) => {
    if (event.event === 'node_start') {
      const nodeId = String(event.data.node_id || '');
      if (nodeId) {
        setNodeRunStatus(nodeId, 'running');
        setNodeDebugMap((prev) => ({
          ...prev,
          [nodeId]: { status: 'running', inputs: event.data.inputs },
        }));
      }
      appendLog(`→ 开始节点 ${nodeId} (${event.data.node_type})`);
    } else if (event.event === 'node_end') {
      const nodeId = String(event.data.node_id || '');
      const status = event.data.status === 'error' ? 'error' : 'success';
      if (nodeId) {
        setNodeRunStatus(nodeId, status as RunNodeStatus);
        setNodeDebugMap((prev) => ({
          ...prev,
          [nodeId]: {
            ...(prev[nodeId] || {}),
            status: status as RunNodeStatus,
            outputs: event.data.outputs as any,
            duration_ms: event.data.duration_ms != null ? Number(event.data.duration_ms) : undefined,
            error: event.data.error != null ? String(event.data.error) : undefined,
          },
        }));
      }
      appendLog(`← 完成节点 ${nodeId}：${event.data.status}（${event.data.duration_ms ?? '?'}ms）`, status as 'info' | 'error');
    } else if (event.event === 'llm_token') {
      // LLM 节点流式 token：追加到该节点的 streamingText，供右侧面板打字机实时显示
      const nodeId = String(event.data.node_id || '');
      const delta = String(event.data.delta || '');
      if (nodeId && delta) {
        setNodeDebugMap((prev) => {
          const cur = prev[nodeId] || { status: 'running' as RunNodeStatus };
          return {
            ...prev,
            [nodeId]: {
              ...cur,
              streamingText: (cur.streamingText || '') + delta,
            },
          };
        });
      }
    } else if (
      event.event === 'prompt_text' ||
      event.event === 'tool_call_start' ||
      event.event === 'tool_call_end'
    ) {
      // T15：Agent Loop 节点的 trace 事件（prompt 原文 / tool 入参出参）
      const nodeId = String(event.data.node_id || '');
      if (nodeId) {
        setNodeDebugMap((prev) => ({
          ...prev,
          [nodeId]: {
            ...(prev[nodeId] || { status: 'running' as RunNodeStatus }),
            trace: [
              ...((prev[nodeId] || {}).trace || []),
              { type: event.event, payload: event.data as Record<string, any> },
            ],
          },
        }));
      }
    } else if (event.event === 'interrupted') {
      // 人审中断：弹审批抽屉
      const approval = event.data.approval as ApprovalInterruptPayload;
      const threadId = String(event.data.thread_id || '');
      const runId = String(event.data.run_id || '');
      setApprovalState({ open: true, payload: approval, threadId, runId });
      setApprovalComment('');
      setApprovalApprover('');
      appendLog(`⏸ 等待人审：${approval.node_title || approval.node_id}（${approval.assignee_role || '未指定角色'}）`);
    } else if (event.event === 'result') {
      appendLog(`✓ 运行完成：${JSON.stringify(event.data.outputs || event.data.output || {})}`);
    } else if (event.event === 'error') {
      appendLog(`✗ 错误：${event.data.message || event.data.error}`, 'error');
    }
  }, [setNodeRunStatus]);

  const doRun = useCallback(async (inputs: Record<string, any>) => {
    if (!id) return;
    setRunning(true);
    setRunLogs([]);
    setNodeDebugMap({});
    clearAllRunStatus();
    // V2：试运行开始后自动展开右下角面板到"日志"Tab
    setPanelTab('logs');
    setPanelOpen(true);
    const appendLog = (text: string, level: 'info' | 'error' = 'info') => {
      const time = new Date().toLocaleTimeString();
      setRunLogs((prev) => [...prev, { time, text, level }]);
    };
    try {
      const ctx = ctxRef.current;
      let graph: Record<string, unknown>;
      if (ctx) {
        const flowgram = toWorkflowJSON(ctx);
        graph = toCozeIR(flowgram, keyToCozeType, graphSchemaVersionRef.current);
      } else {
        graph = {};
      }
      appendLog(`启动试运行，入参：${JSON.stringify(inputs)}`);
      await debugRunAppStream(
        { graph: graph as never, inputs },
        (event) => handleRunEvent(event, appendLog),
      );
      appendLog('试运行结束');
    } catch (err) {
      appendLog(`试运行失败：${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setRunning(false);
    }
  }, [id, clearAllRunStatus, setNodeRunStatus, keyToCozeType, handleRunEvent]);

  // 人审批复后续跑
  const handleApprovalSubmit = useCallback(async (approved: boolean) => {
    const ctx = ctxRef.current;
    if (!ctx || !approvalState.payload) return;
    setApprovalState((prev) => ({ ...prev, open: false }));
    setRunning(true);
    const appendLog = (text: string, level: 'info' | 'error' = 'info') => {
      const time = new Date().toLocaleTimeString();
      setRunLogs((prev) => [...prev, { time, text, level }]);
    };
    try {
      const flowgram = toWorkflowJSON(ctx);
      const graph = toCozeIR(flowgram, keyToCozeType, graphSchemaVersionRef.current);
      appendLog(`${approved ? '✓ 审批通过' : '✗ 审批拒绝'}，续跑...`);
      await debugRunAppStreamResume(
        {
          graph: graph as never,
          thread_id: approvalState.threadId,
          run_id: approvalState.runId || undefined,
          approval: {
            approved,
            comment: approvalComment,
            approver: approvalApprover || 'admin',
          },
        },
        (event) => handleRunEvent(event, appendLog),
      );
      appendLog('试运行结束');
    } catch (err) {
      appendLog(`续跑失败：${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setRunning(false);
    }
  }, [approvalState, approvalComment, approvalApprover, handleRunEvent, keyToCozeType]);

  const handleRun = useCallback(() => {
    if (!id || running) return;
    const params = extractStartParams();
    if (params.length > 0) {
      setStartParams(params);
      const initInputs: Record<string, any> = {};
      params.forEach((p) => { initInputs[p.name] = ''; });
      setRunInputs(initInputs);
      setRunModalOpen(true);
    } else {
      doRun({});
    }
  }, [id, running, extractStartParams, doRun]);

  // 删除连线：line.dispose 会触发 linesManager 的 DELETE_LINE，从而走 onContentChange 自动保存
  const deleteLines = useCallback((lineIds: string[]) => {
    const removed = disposeLinesByIds(ctxRef.current, lineIds);
    selectedLineIdsRef.current = [];
    if (removed > 0) {
      message.success(removed > 1 ? `已删除 ${removed} 条连线` : '连线已删除');
    }
  }, []);

  // ========== 键盘快捷键（U-P1 + U-P6 撤销重做） ==========
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const inInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;
      // Ctrl/Cmd+S：保存
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        scheduleSave();
        return;
      }
      // Ctrl/Cmd+Enter：试运行
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        handleRun();
        return;
      }
      // Ctrl/Cmd+Z：撤销（非输入框时交给 FlowGram history）
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !inInput) {
        e.preventDefault();
        if (e.shiftKey) redo(ctxRef.current);
        else undo(ctxRef.current);
        return;
      }
      // Ctrl/Cmd+Y：重做
      if ((e.ctrlKey || e.metaKey) && e.key === 'y' && !inInput) {
        e.preventDefault();
        redo(ctxRef.current);
        return;
      }
      // Ctrl/Cmd+C / V：复制 / 粘贴节点（不在输入框且无文本选区时生效）
      if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'v') && !inInput) {
        const selection = window.getSelection?.();
        if (selection && !selection.isCollapsed && selection.toString().length > 0) return;
        e.preventDefault();
        if (e.key === 'c') copyNode();
        else pasteNode();
        return;
      }
      // Ctrl/Cmd+A：全选节点（输入框内保留原生全选）
      if ((e.ctrlKey || e.metaKey) && e.key === 'a' && !inInput) {
        e.preventDefault();
        selectAllNodes(ctxRef.current);
        return;
      }
      // Esc：优先关闭浮层，其次清空画布选中（N9-09）
      if (e.key === 'Escape' && !inInput) {
        // 弹窗 / 抽屉的 Esc 交给 antd 处理，避免连带清空选中
        if (renameTarget || deleteNodeOpen || versionDrawerOpen || variablesDrawerOpen || approvalState.open) {
          return;
        }
        if (addNodePopover) {
          setAddNodePopover(null);
          return;
        }
        if (configDrawerOpen) {
          setConfigDrawerOpen(false);
          drawerNodeIdRef.current = null;
          return;
        }
        clearSelection(ctxRef.current);
        setSelectedNodeId(null);
        setSelectedNodeIds([]);
        return;
      }
      // Delete / Backspace：删除选中节点（单选或多选均弹一次确认）
      if ((e.key === 'Delete' || e.key === 'Backspace') && !inInput) {
        const ids = selectedNodeIds.length > 0
          ? selectedNodeIds
          : (selectedNodeId ? [selectedNodeId] : []);
        if (ids.length > 0) {
          e.preventDefault();
          // 捕获阶段截断：避免 FlowGram 内置 Delete 抢在确认弹窗前直接删节点
          e.stopPropagation();
          e.stopImmediatePropagation();
          setDeleteTargetIds(ids);
          setDeleteNodeOpen(true);
          return;
        }
        // 无节点选中时，若选中了连线则直接删除（连线删除无副作用，不需要二次确认）
        const lineIds = selectedLineIdsRef.current.length > 0
          ? selectedLineIdsRef.current
          : getSelection(ctxRef.current).lineIds;
        if (lineIds.length > 0) {
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
          deleteLines(lineIds);
        }
        return;
      }
    };
    // 捕获阶段注册，Delete 需先于画布内部快捷键处理
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [
    scheduleSave, handleRun, copyNode, pasteNode, deleteLines,
    selectedNodeId, selectedNodeIds, addNodePopover, configDrawerOpen,
    renameTarget, deleteNodeOpen, versionDrawerOpen, variablesDrawerOpen, approvalState.open,
  ]);

  // ========== 版本历史（B9） ==========
  const openVersionDrawer = useCallback(async () => {
    if (!id) return;
    setVersionDrawerOpen(true);
    try {
      const list = await listGraphVersions(id);
      setVersions(list);
    } catch {
      message.error('加载版本历史失败');
    }
  }, [id]);

  const handleRollback = useCallback(async (version: number) => {
    if (!id) return;
    try {
      await rollbackGraph(id, version);
      message.success(`已回滚到版本 ${version}`);
      setVersionDrawerOpen(false);
      // 重新加载 graph
      const resp = await getAppGraph(id);
      graphSchemaVersionRef.current = resp.graph_schema_version ?? readSchemaVersion(resp.graph);
      setInitialData(fromCozeIR(resp.graph, cozeTypeToKey));
    } catch (err) {
      message.error(err instanceof Error ? err.message : '回滚失败');
    }
  }, [id, cozeTypeToKey]);

  // ========== 渲染 ==========
  if (!id) return <div style={{ padding: 24 }}>缺少应用 ID</div>;
  if (loadError) return <div style={{ padding: 24, color: CANVAS_TOKENS.dangerDeep }}>加载失败：{loadError}</div>;
  // nodeMetas 未就绪时不要挂载编辑器：节点类型未注册会导致节点 0 尺寸、画布空白
  if (!initialData || !nodeMetaReady) return <div style={{ padding: 24 }}>加载中…</div>;

  const categoryLabels: Record<string, string> = {
    control: '流程控制',
    ai: 'AI',
    logic: '逻辑',
    data: '数据',
    conversation: '会话',
  };

  return (
    <div style={{ display: 'flex', width: '100%', height: 'calc(100vh - 108px)' }}>
      {/* 左侧资源树（V4）：节点库已迁移到底部 +添加节点气泡 */}
      <ResourceSidebar
        appName={id || ''}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() =>
          setSidebarCollapsed((v) => {
            const next = !v;
            // 手动展开后标记，避免窄屏断点监听再次强制折叠
            if (!next) manualSidebarExpandRef.current = true;
            return next;
          })
        }
        onOpenVariables={() => setVariablesDrawerOpen(true)}
        onOpenVersions={openVersionDrawer}
        onOpenConversation={() => message.info('会话管理模块开发中')}
      />

      {/* 画布区域 */}
      <div style={{ flex: 1, position: 'relative' }}>
        <style>{`
          .gedit-playground-container {
            position: relative !important;
            width: 100% !important;
            height: 100% !important;
          }
          @keyframes boxia-pulse {
            0%, 100% { box-shadow: 0 0 0 3px rgba(139,92,246,0.4); }
            50% { box-shadow: 0 0 0 6px rgba(139,92,246,0.15); }
          }
          .boxia-node-running {
            animation: boxia-pulse 1.2s ease-in-out infinite;
          }
          .boxia-node-invalid {
            box-shadow: 0 0 0 3px rgba(239,68,68,0.5) !important;
            border-radius: 8px;
          }
          /* ========== 连线样式（V6 对齐 Coze：主色 #5044fc，选中亮青） ==========
             FlowGram 每条连线渲染两个 path：曲线 + 箭头（V 形折线），二者共用同一套样式。
             选中态由 FlowGram 用 path 的 stroke-width 属性区分（2 → 3），
             因此这里不能再给 stroke-width 加 !important，否则选中态被抹平。 */
          .gedit-flow-activity-edge path {
            stroke: ${CANVAS_TOKENS.line} !important;
            fill: none !important;
            transition: stroke 0.15s, stroke-width 0.15s, filter 0.15s;
          }
          .gedit-flow-activity-edge:hover path {
            stroke: ${CANVAS_TOKENS.lineHover} !important;
          }
          .gedit-flow-activity-edge path[stroke-width='3'],
          .gedit-flow-activity-edge:hover path[stroke-width='3'] {
            stroke: ${CANVAS_TOKENS.lineActive} !important;
            filter: drop-shadow(0 0 4px ${CANVAS_TOKENS.lineActiveGlow});
          }
          /* ========== 端口圆点（对齐 Coze 实机） ==========
             FlowGram 端口 DOM：
             <div data-port-entity-id class="WorkflowPointStyle-xxx">  ← 外层 20x20 命中区
               <div class="bg-circle workflow-bg-circle"/>             ← 白色底圈
               <div class="bg workflow-port-bg workflow-point-bg">    ← 紫色圆点
               <div class="focus-circle"/>
             问题：.bg 默认是 position: relative 的流式元素，旧样式把它缩到 12x12 后
                   仍贴在命中区左上角，圆心与白圈圆心差 4px（用户反馈的"端点未居中"）。
             修复：改成绝对定位 + 50%/负 margin 居中，缩放不会破坏圆心位置。 */
          [data-port-entity-id] {
            width: 20px !important;
            height: 20px !important;
            margin-top: -10px !important;
            margin-left: -10px !important;
            background: transparent !important;
            border: none !important;
          }
          [data-port-entity-id] > .bg-circle,
          [data-port-entity-id] > .workflow-bg-circle {
            width: 20px !important;
            height: 20px !important;
            left: 0 !important;
            top: 0 !important;
            background: #fff !important;
            transform: scale(1) !important;
          }
          [data-port-entity-id] > .bg,
          [data-port-entity-id] > .workflow-port-bg,
          [data-port-entity-id] > .workflow-point-bg {
            position: absolute !important;
            left: 50% !important;
            top: 50% !important;
            width: 12px !important;
            height: 12px !important;
            margin: -6px 0 0 -6px !important;
            background: ${CANVAS_TOKENS.port} !important;
            transform: scale(1) !important;
            border: 2px solid ${CANVAS_TOKENS.white} !important;
            box-shadow: 0 0 0 1px ${CANVAS_TOKENS.port} !important;
            cursor: crosshair !important;
          }
          [data-port-entity-id]:hover > .bg,
          [data-port-entity-id]:hover > .workflow-port-bg,
          [data-port-entity-id].hovered > .bg,
          [data-port-entity-id].hovered > .workflow-port-bg {
            background: ${CANVAS_TOKENS.portHover} !important;
            transform: scale(1.15) !important;
          }
          [data-port-entity-id].linked > .bg,
          [data-port-entity-id].linked > .workflow-port-bg {
            background: ${CANVAS_TOKENS.portLinked} !important;
          }
          /* 输出端口 hover：对齐 Coze 的紫色「+」拖拽提示（输入端口保持圆点） */
          [data-port-entity-id][data-port-entity-type='output']:hover > .bg,
          [data-port-entity-id][data-port-entity-type='output'].hovered > .bg {
            width: 18px !important;
            height: 18px !important;
            margin: -9px 0 0 -9px !important;
            background: ${CANVAS_TOKENS.port} !important;
            transform: scale(1) !important;
            box-shadow: 0 0 0 1px ${CANVAS_TOKENS.port}, 0 0 0 5px ${CANVAS_TOKENS.portRing} !important;
          }
          [data-port-entity-id][data-port-entity-type='output']:hover > .bg::after,
          [data-port-entity-id][data-port-entity-type='output'].hovered > .bg::after {
            content: '+';
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            font-size: 14px;
            font-weight: 400;
            line-height: 1;
          }
          [data-port-entity-id] > .bg > .cross-hair,
          [data-port-entity-id] .focus-circle {
            display: none !important;
          }
          /* 拖线时命中的可落点输入端口（JS 打标，拖拽中 :hover 不可靠） */
          [data-port-entity-id].boxia-port-drop-target > .bg,
          [data-port-entity-id].boxia-port-drop-target > .workflow-port-bg {
            background: ${CANVAS_TOKENS.portDrop} !important;
            transform: scale(1.35) !important;
          }
          [data-port-entity-id].boxia-port-drop-target {
            border-radius: 50% !important;
            box-shadow: 0 0 0 5px ${CANVAS_TOKENS.portDropRing} !important;
          }
          /* RefChipInput 聚焦态 */
          .boxia-ref-chip-input:focus-within {
            border-color: ${CANVAS_TOKENS.accent} !important;
            box-shadow: 0 0 0 2px ${CANVAS_TOKENS.portRingSoft};
          }
        `}</style>

        {/* 底部居中浮条（V3）：缩放 + 适应 + 全屏 | +添加节点 | 试运行 */}
        <CanvasToolbar
          ctxRef={ctxRef}
          zoom={canvasZoom}
          running={running}
          canUndo={historyState.canUndo}
          canRedo={historyState.canRedo}
          onUndo={() => undo(ctxRef.current)}
          onRedo={() => redo(ctxRef.current)}
          onAddNode={() => {
            const playground = document.querySelector('.gedit-playground-container');
            if (!playground) return;
            const rect = playground.getBoundingClientRect();
            setAddNodePopover({
              x: rect.left + rect.width / 2 - 140,
              y: rect.top + rect.height / 2 - 160,
            });
          }}
          onRun={handleRun}
          onExportJson={handleExportJson}
        />

        {/* 多选提示浮条（N9-02）：叠在底部工具条上方 */}
        {selectedNodeIds.length > 1 && (
          <div
            style={{
              position: 'absolute',
              bottom: 68,
              left: '50%',
              transform: 'translateX(-50%)',
              zIndex: CANVAS_TOKENS.z.toolbar,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '6px 12px',
              background: CANVAS_TOKENS.white,
              borderRadius: 10,
              boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
              border: `1px solid ${CANVAS_TOKENS.border}`,
              fontSize: 12,
              color: '#374151',
            }}
          >
            <span>已选中 {selectedNodeIds.length} 个节点</span>
            <Button
              size="small"
              danger
              type="text"
              onClick={() => {
                setDeleteTargetIds(selectedNodeIds);
                setDeleteNodeOpen(true);
              }}
            >
              批量删除
            </Button>
          </div>
        )}

        {/* 画布右键菜单（U-P2） */}
        <CanvasContextMenu
          onAddNode={() => { /* 打开左侧节点库 */ }}
          onAutoLayout={() => message.info('自动排版功能待 FlowGram 插件支持')}
          onFitView={() => { void fitView(ctxRef.current, true); }}
          onDeleteSelected={() => {
            const ids = selectedNodeIds.length > 0
              ? selectedNodeIds
              : (selectedNodeId ? [selectedNodeId] : []);
            if (ids.length > 0) {
              setDeleteTargetIds(ids);
              setDeleteNodeOpen(true);
            } else {
              message.info('请先选中一个节点');
            }
          }}
          onCopyNode={copyNode}
          onPasteNode={pasteNode}
          getLineIdAt={(e) => {
            try {
              const pos = getWorldPosFromMouseEvent(ctxRef.current, e);
              if (!pos) return null;
              return getLineFromMousePos(ctxRef.current, pos)?.id ?? null;
            } catch {
              return null;
            }
          }}
          onDeleteLine={(lineId) => deleteLines([lineId])}
        />

        {/* 空白画布欢迎页 */}
        <EmptyCanvasWelcome visible={nodeCount <= 1} />

        {/* 连线端点弹出节点面板（U-B2） */}
        {addNodePopover && (
          <AddNodePopover
            x={addNodePopover.x}
            y={addNodePopover.y}
            metas={nodeMetas}
            onSelect={(typeKey) => {
              // 有 fromNodeId：从源节点 + 按钮弹出，自动贴源节点右侧；
              // 无 fromNodeId：走"默认贴 START 右侧"逻辑（不再用屏幕坐标反算，避免 zoom 不准导致节点飞出视口）
              addNode(typeKey, addNodePopover?.fromNodeId ? { fromNodeId: addNodePopover.fromNodeId } : {});
              setAddNodePopover(null);
            }}
            onClose={() => setAddNodePopover(null)}
          />
        )}

        {/* 小地图（对齐 Coze）：节点缩略图 + 当前可视区域框 */}
        <MiniMap
          nodes={pickerNodes
            .filter((n) => n.position)
            .map((n) => ({
              id: n.id,
              x: n.position!.x,
              y: n.position!.y,
              color: keyToMeta[n.typeKey]?.color,
            }))}
          viewport={canvasViewport}
          onNavigate={(x, y) => {
            // 点击小地图把相机中心移到对应画布坐标
            scrollToCanvasPoint(ctxRef.current, x, y);
          }}
        />

        {/* V6：保存状态（顶部左侧小字） */}
        <div style={{
          position: 'absolute', top: 12, left: 16, zIndex: 100,
          fontSize: 12,
          color: saveStatus === 'error' ? CANVAS_TOKENS.dangerDeep : saveStatus === 'saving' ? CANVAS_TOKENS.info : CANVAS_TOKENS.run,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: saveStatus === 'error' ? CANVAS_TOKENS.dangerDot : saveStatus === 'saving' ? CANVAS_TOKENS.info : CANVAS_TOKENS.run,
            animation: saveStatus === 'saving' ? 'boxia-pulse 1.2s ease-in-out infinite' : undefined,
          }} />
          {validating && '校验中…'}
          {!validating && saveStatus === 'saving' && '保存中…'}
          {!validating && saveStatus === 'saved' && lastSavedAt && `已保存 ${lastSavedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`}
          {!validating && saveStatus === 'saved' && !lastSavedAt && '已保存'}
          {!validating && saveStatus === 'error' && <span style={{ cursor: 'pointer' }} onClick={() => scheduleSave()}>保存失败，点击重试</span>}
          <span
            style={{
              cursor: 'pointer',
              color: validationIssues.some((i) => i.severity === 'error') ? CANVAS_TOKENS.danger : '#6b7280',
            }}
            onClick={async () => {
              await doValidate();
              setPanelTab('validation');
              setPanelOpen(true);
            }}
          >
            · 校验{validationIssues.length > 0 ? ` ${validationIssues.length}` : ''}
          </span>
        </div>

        {/* 发布按钮（顶部右侧，V5 配色 #7c3aed） */}
        <div style={{
          position: 'absolute', top: 8, right: 16, zIndex: 100,
          display: 'flex', alignItems: 'center', gap: 8,
        }}>
          {publishedVersion != null && (
            <Tag color="green" style={{ marginRight: 0, fontSize: 12 }}>
              ● live v{publishedVersion}
            </Tag>
          )}
          <Button
            type="primary"
            size="small"
            loading={publishing}
            onClick={handlePublish}
            style={{ background: '#7c3aed', borderColor: '#7c3aed' }}
          >
            🚀 发布
          </Button>
        </div>

        {/* 校验问题 + 运行日志 合并面板（V1/V2）：右下角可折叠 Tab 抽屉 */}
        {panelOpen && (
          <div style={{
            position: 'absolute', bottom: 80, right: 16, zIndex: 100,
            width: 400, maxHeight: 360, display: 'flex', flexDirection: 'column',
            background: '#fff', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '8px 12px', borderBottom: '1px solid #f0f0f0',
            }}>
              <TabSwitch
                active={panelTab === 'validation'}
                label={`校验${validationIssues.length > 0 ? ` (${validationIssues.length})` : ''}`}
                onClick={() => setPanelTab('validation')}
              />
              <TabSwitch
                active={panelTab === 'logs'}
                label={`日志${runLogs.length > 0 ? ` (${runLogs.length})` : ''}`}
                onClick={() => setPanelTab('logs')}
              />
              <span style={{ marginLeft: 'auto', cursor: 'pointer', color: '#999' }} onClick={() => setPanelOpen(false)}>✕</span>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
              {panelTab === 'validation' && (
                validationIssues.length === 0 ? (
                  <div style={{ color: '#9ca3af', fontSize: 12, textAlign: 'center', padding: 16 }}>
                    暂无校验问题
                  </div>
                ) : (
                  validationIssues.map((issue, idx) => (
                    <div key={idx} style={{
                      fontSize: 12, padding: '6px 0',
                      color: issue.severity === 'error' ? CANVAS_TOKENS.danger : CANVAS_TOKENS.warning,
                      display: 'flex', gap: 8, alignItems: 'flex-start', cursor: 'pointer',
                      borderBottom: '1px dashed #f3f4f6',
                    }}
                      onClick={() => {
                        if (!issue.node_id) return;
                        const el = document.getElementById(issue.node_id);
                        el?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
                      }}
                    >
                      <span>{issue.severity === 'error' ? '●' : '▲'}</span>
                      <span style={{ flex: 1 }}>{issue.message}</span>
                      {issue.node_id && (
                        <Tag style={{ fontSize: 11, marginRight: 0 }}>{issue.node_id}</Tag>
                      )}
                    </div>
                  ))
                )
              )}
              {panelTab === 'logs' && (
                runLogs.length === 0 ? (
                  <div style={{ color: '#9ca3af', fontSize: 12, textAlign: 'center', padding: 16 }}>
                    暂无运行日志
                  </div>
                ) : (
                  <div style={{
                    background: 'rgba(0,0,0,0.85)', color: '#d9d9d9',
                    borderRadius: 6, padding: 12, fontFamily: 'monospace', fontSize: 12,
                    maxHeight: 280, overflowY: 'auto',
                  }}>
                    {runLogs.map((log, i) => (
                      <div key={i} style={{ color: log.level === 'error' ? CANVAS_TOKENS.dangerDot : '#d9d9d9' }}>
                        <span style={{ color: '#666' }}>[{log.time}]</span> {log.text}
                      </div>
                    ))}
                  </div>
                )
              )}
            </div>
          </div>
        )}

        {/* 子图面包屑（B6） */}
        {subgraphStack.length > 0 && (
          <div style={{
            position: 'absolute', top: 48, left: 16, zIndex: 100,
            display: 'flex', alignItems: 'center', gap: 8,
            background: '#fff', borderRadius: 8, padding: '6px 12px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)', fontSize: 13,
          }}>
            <Button
              type="link"
              size="small"
              onClick={() => exitSubgraph(subgraphStack.length)}
            >
              返回根图
            </Button>
            <span style={{ color: '#ccc' }}>/</span>
            {subgraphBreadcrumb.map((item, idx) => (
              <span key={item.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                {idx > 0 && <span style={{ color: '#ccc' }}>/</span>}
                {idx === subgraphBreadcrumb.length - 1 ? (
                  <strong>{item.title}</strong>
                ) : (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => exitSubgraph(subgraphStack.length - idx - 1)}
                  >
                    {item.title}
                  </Button>
                )}
              </span>
            ))}
          </div>
        )}

        <FreeLayoutEditor
          key={editorKey}
          nodeRegistries={nodeRegistries}
          materials={{ renderNodes: renderNodes as any }}
          initialData={initialData}
          // T9-07：对齐 Coze —— 普通左键拖拽平移（下方自绘），Shift+拖拽才框选
          selectBox={{ enabled: true, canSelect: (e) => e.shiftKey }}
          // T9-07：撤销/重做依赖 history 插件，未开启时 ctx.history 取值会抛异常
          history={{ enable: true, limit: 100 }}
          onLoad={(ctx) => {
            ctxRef.current = ctx;
            (window as any).__flowCtx = ctx;
            setNodeCount(getNodeCount(ctx));
            refreshPickerNodes();

            // 同步 FlowGram 原生选中集合（单击 / Shift 点选 / 框选）到 React 状态
            selectionDisposableRef.current?.dispose?.();
            selectionDisposableRef.current = subscribeSelection(ctx, (snapshot) => {
              selectedLineIdsRef.current = snapshot.lineIds;
              setSelectedNodeIds(snapshot.nodeIds);
              if (snapshot.nodeIds.length === 1) {
                setSelectedNodeId(snapshot.nodeIds[0] ?? null);
                const meta = keyToMetaRef.current[snapshot.nodeTypeKeys[0] ?? ''];
                if (meta) setSelectedNodeMeta(meta);
              } else {
                setSelectedNodeId(null);
                // 多选或清空选中时收起配置抽屉，避免内容与选中态错位
                if (snapshot.nodeIds.length !== 0 || drawerNodeIdRef.current) {
                  setConfigDrawerOpen(false);
                  drawerNodeIdRef.current = null;
                }
              }
              if (drawerNodeIdRef.current && !snapshot.nodeIds.includes(drawerNodeIdRef.current)) {
                setConfigDrawerOpen(false);
                drawerNodeIdRef.current = null;
              }
            });

            // 订阅 history 变更：驱动底部撤销/重做按钮可用态
            historyDisposableRef.current?.dispose?.();
            historyDisposableRef.current = subscribeHistory(ctx, setHistoryState);

            // 空白处左键拖拽平移（Shift+拖拽留给框选）
            panCleanupRef.current?.();
            panCleanupRef.current = setupCanvasPan(ctx);

            // 订阅画布缩放/滚动：驱动小地图相机框和底部缩放百分比
            viewportDisposablesRef.current.forEach((d) => d.dispose?.());
            viewportDisposablesRef.current = [subscribeViewport(ctx, syncCanvasViewport)];
            syncCanvasViewport();

            // 首次加载布局完成后适应视图，避免节点落在视口外
            setTimeout(() => { void fitView(ctx, false).then(syncCanvasViewport); }, 100);
          }}
          onContentChange={() => {
            scheduleSave();
            setNodeCount(getNodeCount(ctxRef.current));
            refreshPickerNodes();
          }}
          canAddLine={canAddLine}
          canDeleteLine={() => true}
          canDeleteNode={(_ctx, node) => {
            const typeKey = getNodeTypeKey(node);
            if (!canDelete(keyToMeta[typeKey], typeKey)) {
              message.warning('该节点不允许删除');
              return false;
            }
            return true;
          }}
          onDragLineEnd={async (ctx: FlowContext, params: any) => {
            // 拖线到空白处（没有 toPort）时弹出节点选择面板
            // mousePos 是画布世界坐标，toFixedPos 才能转成 Popover 需要的屏幕坐标
            if (params?.toPort || !params?.mousePos) return;
            // 点击/拖动已有连线时 FlowGram 也会回调 onDragLineEnd（originLine 非空），不是新建连线
            if (params?.originLine) return;
            // 拖到端口/节点上时 FlowGram 会自动连线，但多输入端口节点的 toPort 可能仍为空，
            // 这里再按落点判断一次，避免连完线又弹出节点面板
            if (getPortFromMousePos(ctx, params.mousePos)) return;
            const nearbyLine = getLineFromMousePos(ctx, params.mousePos);
            // 拖拽中的临时连线终点就在鼠标处，会命中它自己，需按 id 排除
            if (nearbyLine && nearbyLine.id !== params?.line?.id) return;
            const hitNode = getNodeFromMousePos(ctx, params.mousePos);
            if (hitNode && hitNode.flowNodeType !== 'root') return;
            const win = worldToScreen(ctx, params.mousePos);
            if (!win) return;
            const fromPort = params.fromPort as { node?: { id?: string } } | undefined;
            const POPOVER_W = 320;
            const POPOVER_H = 460;
            const x = Math.min(Math.max(8, win.x - POPOVER_W / 2), window.innerWidth - POPOVER_W - 16);
            const y = Math.min(Math.max(8, win.y + 12), window.innerHeight - POPOVER_H - 16);
            setAddNodePopover({ x, y, fromNodeId: fromPort?.node?.id });
          }}
        />

        {/* U-N4 对齐辅助线：拖拽节点时显示对齐参考线（只提示不吸附） */}
        <AlignGuides ctxRef={ctxRef} />

        {/* 右侧调试面板（B8） */}
        {Object.keys(nodeDebugMap).length > 0 && (
          <div style={{
            position: 'absolute', top: 48, right: 16, zIndex: 100,
            width: 320, maxHeight: 'calc(100% - 120px)', overflowY: 'auto',
            background: '#fff', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            padding: 12,
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              节点调试
            </div>
            <Collapse
              size="small"
              items={Object.entries(nodeDebugMap).map(([nodeId, info]) => {
                const statusColor = info.status === 'error' ? '#ff4d4f' : info.status === 'success' ? '#52c41a' : '#1677ff';
                return {
                  key: nodeId,
                  label: (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: statusColor }} />
                      <span style={{ fontFamily: 'monospace' }}>{nodeId}</span>
                      {info.duration_ms != null && (
                        <span style={{ color: '#999', marginLeft: 'auto' }}>{info.duration_ms}ms</span>
                      )}
                    </div>
                  ),
                  children: (
                    <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
                      {info.inputs != null && (
                        <div style={{ marginBottom: 6 }}>
                          <div style={{ color: '#999' }}>输入：</div>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            {JSON.stringify(info.inputs, null, 2)}
                          </pre>
                        </div>
                      )}
                      {info.streamingText != null && info.streamingText !== '' && (
                        <div style={{ marginBottom: 6 }}>
                          <div style={{ color: '#1677ff' }}>流式输出：</div>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            {info.streamingText}
                          </pre>
                        </div>
                      )}
                      {info.outputs != null && (
                        <div style={{ marginBottom: 6 }}>
                          <div style={{ color: '#999' }}>输出：</div>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                            {JSON.stringify(info.outputs, null, 2)}
                          </pre>
                        </div>
                      )}
                      {info.error && (
                        <div style={{ color: '#ff4d4f' }}>
                          <div>错误：</div>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{info.error}</pre>
                        </div>
                      )}
                      {info.trace && info.trace.length > 0 && (
                        <div style={{ marginTop: 6, borderTop: '1px dashed #eee', paddingTop: 6 }}>
                          <div style={{ color: '#999', marginBottom: 4 }}>运行 trace（{info.trace.length} 条）：</div>
                          {info.trace.map((t, idx) => (
                            <TraceEntry key={idx} entry={t} />
                          ))}
                        </div>
                      )}
                    </div>
                  ),
                };
              })}
            />
          </div>
        )}
      </div>

      {/* 节点配置抽屉 */}
      <Drawer
        title={selectedNodeMeta ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <NodeIcon
              typeKey={selectedNodeMeta.type_key}
              color={selectedNodeMeta.color}
              icon={selectedNodeMeta.icon}
              size={28}
            />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 15, fontWeight: 600, lineHeight: '20px' }}>
                {selectedNodeMeta.title}
              </div>
              {selectedNodeMeta.description && (
                <div style={{
                  fontSize: 12, color: '#6b7280', fontWeight: 400, lineHeight: '16px',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {selectedNodeMeta.description}
                </div>
              )}
            </div>
          </div>
        ) : ''}
        open={configDrawerOpen && !!selectedNodeId}
        onClose={() => setConfigDrawerOpen(false)}
        width="min(480px, 92vw)"
        extra={
          selectedNodeId && selectedNodeMeta && canDelete(selectedNodeMeta) ? (
            <Button danger size="small" onClick={() => {
              setDeleteTargetIds(selectedNodeId ? [selectedNodeId] : []);
              setDeleteNodeOpen(true);
            }}>
              删除节点
            </Button>
          ) : undefined
        }
      >
        {selectedNodeMeta && (
          <NodeConfigForm
            nodeMeta={selectedNodeMeta}
            values={configValues}
            onChange={handleConfigChange}
            pickerNodes={pickerNodes}
            currentNodeId={selectedNodeId}
            keyToMeta={keyToMeta}
            outputs={nodeOutputs}
            onOutputsChange={handleOutputsChange}
            datasetOptions={datasetOptions}
            upstreamInputs={upstreamInputs}
            onAddNext={(typeKey) => {
              // V10：配置抽屉里点"下一步"，以当前选中节点为 source 自动连线
              const fromNodeId = selectedNodeId;
              setSelectedNodeId(null);
              setConfigDrawerOpen(false);
              addNode(typeKey, { fromNodeId });
            }}
          />
        )}
        <div style={{ marginTop: 16 }}>
          <Tag color="blue">节点 ID：{selectedNodeId}</Tag>
        </div>
      </Drawer>

      {/* 卡片「⋯」重命名弹窗（N9-07） */}
      <Modal
        title="重命名节点"
        open={Boolean(renameTarget)}
        onOk={confirmCardRename}
        onCancel={() => setRenameTarget(null)}
        okText="保存"
        cancelText="取消"
      >
        <Input
          autoFocus
          maxLength={60}
          placeholder="节点名称"
          value={renameTarget?.value ?? ''}
          onChange={(e) => {
            const next = e.target.value;
            setRenameTarget((prev) => (prev ? { ...prev, value: next } : prev));
          }}
          onPressEnter={confirmCardRename}
        />
      </Modal>

      {/* 删除节点确认弹窗（U-S3） */}
      <Modal
        title={deleteTargetIds.length > 1 ? '批量删除节点' : '删除节点'}
        open={deleteNodeOpen}
        onOk={confirmDeleteNode}
        onCancel={() => { setDeleteNodeOpen(false); setDeleteTargetIds([]); }}
        okText="删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <div>
          {deleteTargetIds.length > 1 ? (
            <span>
              确定要删除选中的 <Tag color="blue">{deleteTargetIds.length}</Tag> 个节点吗？
            </span>
          ) : (
            <span>
              确定要删除节点 <Tag color="blue">{selectedNodeMeta?.title || deleteTargetIds[0] || selectedNodeId}</Tag> 吗？
            </span>
          )}
          <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
            与该节点相连的所有连线将一并删除，此操作不可撤销。
          </div>
        </div>
      </Modal>

      {/* 试运行入参弹窗（B7 + T18 多模态） */}
      <Modal
        title="试运行入参"
        open={runModalOpen}
        onCancel={() => setRunModalOpen(false)}
        onOk={() => {
          setRunModalOpen(false);
          doRun(runInputs);
        }}
        okText="开始运行"
        cancelText="取消"
        destroyOnHidden
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {startParams.map((p) => {
            const type = (p.type || 'string').toLowerCase();
            const isImageOrFile = type === 'image' || type === 'file';
            if (!isImageOrFile) {
              return (
                <div key={p.name}>
                  <Typography.Text type="secondary">{p.name}</Typography.Text>
                  <Input
                    value={runInputs[p.name] ?? ''}
                    onChange={(e) => setRunInputs((prev) => ({ ...prev, [p.name]: e.target.value }))}
                    placeholder={p.type || 'string'}
                  />
                </div>
              );
            }
            // T18：image/file 类型 → 上传组件，文件读为 dataURL，多图用逗号分隔
            const currentValue = (runInputs[p.name] as string) || '';
            const currentUrls = currentValue ? currentValue.split(',').filter(Boolean) : [];
            return (
              <div key={p.name}>
                <Typography.Text type="secondary">
                  {p.name}
                  <Tag color="purple" style={{ marginLeft: 8 }}>{p.type}</Tag>
                </Typography.Text>
                <Upload
                  accept={type === 'image' ? 'image/*' : undefined}
                  listType="picture"
                  multiple
                  beforeUpload={(file) => {
                    const reader = new FileReader();
                    reader.onload = () => {
                      const dataUrl = String(reader.result || '');
                      setRunInputs((prev) => {
                        const prevVal = (prev[p.name] as string) || '';
                        const urls = prevVal ? prevVal.split(',').filter(Boolean) : [];
                        urls.push(dataUrl);
                        return { ...prev, [p.name]: urls.join(',') };
                      });
                    };
                    reader.readAsDataURL(file);
                    return false; // 阻止自动上传
                  }}
                  onRemove={(file) => {
                    // 简化：onRemove 无法精确匹配 dataURL，这里改为清空当前字段让用户重选
                    setRunInputs((prev) => ({ ...prev, [p.name]: '' }));
                    return true;
                  }}
                  fileList={currentUrls.map((url, idx) => ({
                    uid: String(idx),
                    name: `upload-${idx + 1}`,
                    status: 'done' as const,
                    url,
                  })) as UploadFile[]}
                >
                  <Button>上传{type === 'image' ? '图片' : '文件'}</Button>
                </Upload>
              </div>
            );
          })}
        </Space>
      </Modal>

      {/* 变量引用抽屉（U-L2） */}
      <VariablesDrawer
        open={variablesDrawerOpen}
        onClose={() => setVariablesDrawerOpen(false)}
        nodes={pickerNodes}
        keyToMeta={keyToMeta}
      />

      {/* 版本历史抽屉（B9） */}
      <Drawer
        title="版本历史"
        open={versionDrawerOpen}
        onClose={() => setVersionDrawerOpen(false)}
        width="min(480px, 92vw)"
      >
        {versions.length === 0 ? (
          <Typography.Text type="secondary">暂无历史版本</Typography.Text>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            {versions.map((v, idx) => (
              <div
                key={v.id}
                style={{
                  padding: 12, border: '1px solid #f0f0f0', borderRadius: 8,
                  background: idx === 0 ? '#f6ffed' : '#fff',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <Tag color={idx === 0 ? 'green' : 'default'}>v{v.version}</Tag>
                  {idx === 0 && <Tag color="blue">当前</Tag>}
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
                    {new Date(v.created_at).toLocaleString()}
                  </Typography.Text>
                </div>
                {v.changelog && (
                  <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{v.changelog}</div>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {v.created_by && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      by {v.created_by}
                    </Typography.Text>
                  )}
                  {idx !== 0 && (
                    <Button
                      size="small"
                      danger
                      style={{ marginLeft: 'auto' }}
                      onClick={() => handleRollback(v.version)}
                    >
                      回滚到此版本
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </Space>
        )}
      </Drawer>

      {/* 人审审批抽屉（B11） */}
      <Drawer
        title={approvalState.payload ? `审批：${approvalState.payload.node_title || approvalState.payload.node_id}` : '审批'}
        open={approvalState.open}
        onClose={() => setApprovalState((prev) => ({ ...prev, open: false }))}
        width="min(480px, 92vw)"
      >
        {approvalState.payload && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {approvalState.payload.assignee_role && (
              <div>
                <Typography.Text type="secondary">审批人角色</Typography.Text>
                <div><Tag color="orange">{approvalState.payload.assignee_role}</Tag></div>
              </div>
            )}
            {approvalState.payload.instructions && (
              <div>
                <Typography.Text type="secondary">审批说明</Typography.Text>
                <div style={{ padding: 8, background: '#fafafa', borderRadius: 6, fontSize: 13 }}>
                  {approvalState.payload.instructions}
                </div>
              </div>
            )}
            {approvalState.payload.snapshot && (
              <div>
                <Typography.Text type="secondary">节点输入快照</Typography.Text>
                <pre style={{
                  margin: 0, padding: 8, background: '#fafafa', borderRadius: 6,
                  fontSize: 11, maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap',
                }}>
                  {JSON.stringify(approvalState.payload.snapshot, null, 2)}
                </pre>
              </div>
            )}
            <div>
              <Typography.Text type="secondary">审批人</Typography.Text>
              <Input
                value={approvalApprover}
                onChange={(e) => setApprovalApprover(e.target.value)}
                placeholder="你的名字（默认 admin）"
              />
            </div>
            <div>
              <Typography.Text type="secondary">审批意见</Typography.Text>
              <Input.TextArea
                rows={3}
                value={approvalComment}
                onChange={(e) => setApprovalComment(e.target.value)}
                placeholder="通过 / 拒绝的原因"
              />
            </div>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button danger onClick={() => handleApprovalSubmit(false)}>
                拒绝
              </Button>
              <Button type="primary" onClick={() => handleApprovalSubmit(true)}>
                通过
              </Button>
            </Space>
          </Space>
        )}
      </Drawer>
    </div>
  );
}
