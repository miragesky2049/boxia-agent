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
import { Drawer, Input, Button, Select, Tag, Space, Typography, InputNumber, Popover, Tree, Modal, Collapse, message, Upload, AutoComplete } from 'antd';
import type { UploadFile } from 'antd';
import type { TreeProps } from 'antd';
import { getAppGraph, saveAppGraph, debugRunAppStream, debugRunAppStreamResume, validateGraph, listGraphVersions, rollbackGraph, publishGraph, type GraphValidationIssue, type GraphVersionItem, type ApprovalInterruptPayload } from '../../api/apps';
import { ApiError } from '../../api/client';
import { getNodeMeta, type NodeMeta } from '../../api/nodeMeta';
import { listAvailableModels, type ModelCatalogItem } from '../../api/models';
import { listDatasets, type DatasetItem } from '../../api/datasets';
import { NodeCard } from './components/NodeCard';
import { CanvasToolbar } from './components/CanvasToolbar';
import { EmptyCanvasWelcome } from './components/EmptyCanvasWelcome';
import { groupConfigFields } from './components/configSections';
import { VariablesDrawer } from './components/VariablesDrawer';
import { usePortTooltips } from './components/usePortTooltips';
import { CanvasContextMenu } from './components/CanvasContextMenu';
import { AddNodePopover } from './components/AddNodePopover';
import { MiniMap } from './components/MiniMap';
import { RefChipInput } from './components/RefChipInput';
import { CodeEditor } from './components/CodeEditor';

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

// ========== 节点渲染组件（双击打开配置） ==========
function makeNodeRenderer(
  meta: NodeMeta,
  _ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>,
  onNodeDoubleClick: (node: WorkflowNodeEntity) => void,
) {
  return function NodeRenderer({ node }: { node: WorkflowNodeEntity }) {
    const nodeData = (node as unknown as { data?: Record<string, any> }).data || {};
    const title = nodeData.title || meta.title;

    // Comment 便签：黄色便签块，显示 content 文本，不显示端口和节点按钮样式
    if (meta.type_key === 'comment') {
      const content = String(nodeData.content || title || '双击编辑便签');
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

    return (
      <WorkflowNodeRenderer node={node}>
        <NodeCard
          typeKey={meta.type_key}
          color={meta.color}
          title={title}
          config={nodeData.config}
          onDoubleClick={() => onNodeDoubleClick(node)}
        />
      </WorkflowNodeRenderer>
    );
  };
}

// ========== 默认图 ==========
const DEFAULT_GRAPH: WorkflowJSON = {
  nodes: [
    {
      id: 'start-1',
      type: 'start',
      meta: { position: { x: 200, y: 200 } },
      data: {},
    } as WorkflowJSON['nodes'][number],
  ],
  edges: [],
};

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
    options: Array<{ value: string }>;
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
          options={field.options.map((o) => ({ value: o.value, label: o.value }))}
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
    case 'textarea':
    case 'tool_list':
    case 'parameter_list':
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
              支持变量参数：https://api.example.com/users/<span style={{ color: '#6366f1' }}>{'{{node.output.id}}'}</span>
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

      {groupConfigFields(nodeMeta.type_key, nodeMeta.config_fields).map((section) => (
        <div key={section.title} style={{ marginTop: 4 }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: '#374151',
            marginBottom: 8, paddingBottom: 4, borderBottom: '1px solid #f0f0f0',
          }}>
            {section.title}
          </div>
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            {section.fields.map((field) => (
              <div key={field.name}>
                <Typography.Text type="secondary">
                  {field.required && <span style={{ color: '#ff4d4f' }}>* </span>}
                  {field.label}
                </Typography.Text>
                {field.description && (
                  <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>{field.description}</div>
                )}
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
        </div>
      ))}

      <div>
        <Typography.Text type="secondary">输出字段（outputs）</Typography.Text>
        <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>
          自定义本节点产出的字段列表，保存后写入 node.data.outputs
        </div>
        <OutputsEditor value={outputs} onChange={onOutputsChange} />
      </div>
    </Space>
  );
}

// ========== 页面组件 ==========
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export default function AppEditPage() {
  const { id } = useParams<{ id: string }>();
  const [initialData, setInitialData] = useState<WorkflowJSON | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [lastSavedAt, setLastSavedAt] = useState<Date | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeMeta, setSelectedNodeMeta] = useState<NodeMeta | null>(null);
  const [configValues, setConfigValues] = useState<NodeConfigValues>({});
  const [nodeOutputs, setNodeOutputs] = useState<OutputFieldItem[]>([]);
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
  const [nodeCount, setNodeCount] = useState(0);
  const [deleteNodeOpen, setDeleteNodeOpen] = useState(false);
  const [variablesDrawerOpen, setVariablesDrawerOpen] = useState(false);
  const [addNodePopover, setAddNodePopover] = useState<{ x: number; y: number } | null>(null);
  const [datasetOptions, setDatasetOptions] = useState<DatasetItem[]>([]);
  usePortTooltips();
  const ctxRef = useRef<FreeLayoutPluginContext | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const nodeCounterRef = useRef<Record<string, number>>({});

  // ========== 子图导航（B6） ==========
  // rootGraphRef 持有完整嵌套 WorkflowJSON（每个子图节点的 data.subgraph）
  // subgraphStack 记录从 root 到当前编辑层的 node_id 路径；空数组 = 编辑 root
  // editorKey 强制 FreeLayoutEditor 重挂载（切换层级时 initialData 改变）
  const rootGraphRef = useRef<WorkflowJSON>(DEFAULT_GRAPH);
  const [subgraphStack, setSubgraphStack] = useState<string[]>([]);
  const [editorKey, setEditorKey] = useState(0);
  const [subgraphBreadcrumb, setSubgraphBreadcrumb] = useState<Array<{ id: string; title: string }>>([]);

  // 把当前 FreeLayoutEditor 的 JSON 回写到 rootGraphRef 对应层级
  const persistCurrentEditor = useCallback(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const json = ctx.document.toJSON() as unknown as WorkflowJSON;
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

  // ========== 节点注册表 ==========
  const nodeRegistries: WorkflowNodeRegistry[] = useMemo(() => {
    return nodeMetas.map((meta) => ({
      type: meta.type_key,
      meta: {
        defaultPorts: [
          ...meta.inputs.map((p) => ({ id: p.name, type: 'input' as const })),
          ...meta.outputs.map((p) => ({ id: p.name, type: 'output' as const })),
        ],
        size: meta.type_key === 'comment'
          ? { width: 220, height: 100 }
          : { width: 220, height: 52 },
        renderKey: meta.type_key,
      },
    }));
  }, [nodeMetas]);

  // ========== 加载图 ==========
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        try {
          const resp = await getAppGraph(id);
          if (cancelled) return;
          setPublishedVersion(resp.published_graph_version ?? null);
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
  }, [id, cozeTypeToKey]);

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
      const cozeIR = toCozeIR(flowgram, keyToCozeType);
      const result = await validateGraph(cozeIR as never);
      setValidationIssues(result.issues);
      collectIssuesForNodes(result.issues);
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
        const issues = await doValidate();
        const hasError = issues.some((i) => i.severity === 'error');
        if (hasError) {
          setSaveStatus('error');
          return;
        }
        const flowgram = collectFullGraph();
        const cozeIR = toCozeIR(flowgram, keyToCozeType);
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
  }, [id, scheduleSave]);

  // ========== 添加节点 ==========
  const addNode = useCallback((typeKey: string) => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const meta = keyToMeta[typeKey];
    if (!meta) return;
    nodeCounterRef.current[typeKey] = (nodeCounterRef.current[typeKey] ?? 0) + 1;
    const nodeId = `${typeKey}-${Date.now().toString(36)}-${nodeCounterRef.current[typeKey]}`;
    const offsetX = 120 + Math.random() * 200;
    const offsetY = 100 + Math.random() * 150;
    const root = ctx.document.getNode('root');
    ctx.document.addNode({
      id: nodeId,
      type: meta.type_key,
      meta: { position: { x: 300 + offsetX, y: 200 + offsetY } },
      data: { title: meta.title, config: {} },
      parent: root,
    });
  }, [keyToMeta]);

  // ========== 双击节点打开配置 ==========
  const refreshPickerNodes = useCallback(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const json = ctx.document.toJSON() as unknown as WorkflowJSON;
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
    const prefix = node.id.split('-')[0];
    const nodeTypeKey = String(node.type || prefix || '');
    const nodeData = ((node as unknown as { data?: { title?: string; config?: NodeConfigValues; outputs?: unknown[] } }).data || {});

    // 子图节点：双击直接进入子图编辑
    if (SUBGRAPH_NODE_TYPES.has(nodeTypeKey)) {
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
        // 同步回写到节点 data（让 persistCurrentEditor 能拿到）
        (node as unknown as { data: Record<string, unknown> }).data = {
          ...nodeData,
          subgraph: initSubgraph,
        };
      }
      enterSubgraph(node.id, nodeData.title || nodeTypeKey);
      return;
    }

    setSelectedNodeId(node.id);
    const meta = prefix ? keyToMeta[prefix] : undefined;
    if (meta) {
      setSelectedNodeMeta(meta);
    }
    setConfigValues({
      title: nodeData.title,
      ...(nodeData.config || {}),
    });
    setNodeOutputs(parseOutputsValue(nodeData.outputs));
    refreshPickerNodes();
  }, [keyToMeta, refreshPickerNodes, enterSubgraph]);

  // ========== 删除节点（U-S3） ==========
  const confirmDeleteNode = useCallback(() => {
    const ctx = ctxRef.current as any;
    const nodeId = selectedNodeId;
    if (!ctx || !nodeId) return;
    try {
      const node = ctx.document?.getNode?.(nodeId);
      if (node && typeof node.remove === 'function') {
        node.remove();
      } else if (typeof ctx.document?.removeNode === 'function') {
        ctx.document.removeNode(nodeId);
      } else {
        message.error('当前画布不支持删除节点');
        return;
      }
      message.success('节点已删除');
    } catch (err) {
      message.error('删除节点失败');
    }
    setSelectedNodeId(null);
    setDeleteNodeOpen(false);
    scheduleSave();
  }, [selectedNodeId, scheduleSave]);

  const renderNodes = useMemo(() => {
    return Object.fromEntries(
      nodeMetas.map((meta) => [
        meta.type_key,
        makeNodeRenderer(meta, ctxRef, handleNodeDoubleClick) as unknown as React.ComponentType<any>,
      ]),
    ) as Record<string, React.ComponentType<any>>;
  }, [nodeMetas, handleNodeDoubleClick]);

  // ========== 抽屉配置变更 ==========
  const handleConfigChange = useCallback((patch: Partial<NodeConfigValues>) => {
    setConfigValues((prev) => {
      const next = { ...prev, ...patch };
      const ctx = ctxRef.current;
      if (ctx && selectedNodeId) {
        const node = ctx.document.getNode(selectedNodeId) as unknown as { data?: Record<string, unknown> };
        if (node) {
          node.data = {
            ...(node.data || {}),
            title: next.title,
            config: next,
          };
        }
      }
      return next;
    });
  }, [selectedNodeId]);

  const handleOutputsChange = useCallback((next: OutputFieldItem[]) => {
    setNodeOutputs(next);
    const ctx = ctxRef.current;
    if (ctx && selectedNodeId) {
      const node = ctx.document.getNode(selectedNodeId) as unknown as { data?: Record<string, unknown> };
      if (node) {
        node.data = {
          ...(node.data || {}),
          outputs: next.map((it) => ({
            name: it.name,
            type: it.type,
            ...(it.description ? { description: it.description } : {}),
          })),
        };
      }
    }
  }, [selectedNodeId]);

  // ========== 连线校验：只能 output → input ==========
  const canAddLine = useCallback((
    _ctx: FreeLayoutPluginContext,
    fromPort: WorkflowPortEntity,
    toPort: WorkflowPortEntity,
    _lines: WorkflowLinesManager,
    silent?: boolean,
  ) => {
    const fromType = (fromPort as unknown as { portType?: string }).portType;
    const toType = (toPort as unknown as { portType?: string }).portType;
    const ok = fromType === 'output' && toType === 'input';
    if (!ok && !silent) {
      message.warning('只能从输出端口连到输入端口');
    }
    return ok;
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
    const flowgram = ctx.document.toJSON() as unknown as WorkflowJSON;
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
    const appendLog = (text: string, level: 'info' | 'error' = 'info') => {
      const time = new Date().toLocaleTimeString();
      setRunLogs((prev) => [...prev, { time, text, level }]);
    };
    try {
      const ctx = ctxRef.current;
      let graph: Record<string, unknown>;
      if (ctx) {
        const flowgram = ctx.document.toJSON() as unknown as WorkflowJSON;
        graph = toCozeIR(flowgram, keyToCozeType);
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
      const flowgram = ctx.document.toJSON() as unknown as WorkflowJSON;
      const graph = toCozeIR(flowgram, keyToCozeType);
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
        const ctx = ctxRef.current as any;
        if (e.shiftKey) {
          ctx?.history?.redo?.();
        } else {
          ctx?.history?.undo?.();
        }
        return;
      }
      // Ctrl/Cmd+Y：重做
      if ((e.ctrlKey || e.metaKey) && e.key === 'y' && !inInput) {
        e.preventDefault();
        const ctx = ctxRef.current as any;
        ctx?.history?.redo?.();
        return;
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [scheduleSave, handleRun]);

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
      setInitialData(fromCozeIR(resp.graph, cozeTypeToKey));
    } catch (err) {
      message.error(err instanceof Error ? err.message : '回滚失败');
    }
  }, [id, cozeTypeToKey]);

  // ========== 渲染 ==========
  if (!id) return <div style={{ padding: 24 }}>缺少应用 ID</div>;
  if (loadError) return <div style={{ padding: 24, color: '#d4380d' }}>加载失败：{loadError}</div>;
  if (!initialData) return <div style={{ padding: 24 }}>加载中…</div>;

  const categoryLabels: Record<string, string> = {
    control: '流程控制',
    ai: 'AI',
    logic: '逻辑',
    data: '数据',
    conversation: '会话',
  };

  return (
    <div style={{ display: 'flex', width: '100%', height: 'calc(100vh - 108px)' }}>
      {/* 左侧节点面板 */}
      <div className="boxia-left-panel" style={{
        width: 200, padding: 12, background: '#fafafa',
        borderRight: '1px solid #f0f0f0',
        display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto',
      }}>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>节点库</div>
        {Object.entries(nodeMetaCategories).map(([category, metas]) => (
          <div key={category} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 11, color: '#999', marginBottom: 4 }}>
              {categoryLabels[category] || category}
            </div>
            {metas.map((meta) => (
              <button
                key={meta.type_key}
                onClick={() => addNode(meta.type_key)}
                disabled={meta.type_key === 'start'}
                style={{
                  padding: '6px 10px', background: '#fff',
                  border: '1px solid #d9d9d9', borderRadius: 6,
                  cursor: meta.type_key === 'start' ? 'not-allowed' : 'pointer',
                  fontSize: 12, color: meta.color, textAlign: 'left',
                  opacity: meta.type_key === 'start' ? 0.5 : 1,
                  display: 'flex', alignItems: 'center', gap: 6,
                }}
              >
                <span style={{
                  display: 'inline-block', width: 6, height: 6,
                  borderRadius: '50%', background: meta.color,
                }} />
                {meta.title}
              </button>
            ))}
          </div>
        ))}

        <div style={{ marginTop: 'auto', paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
          <Button
            block
            loading={validating}
            onClick={() => doValidate()}
            style={{ marginBottom: 8 }}
          >
            ✔ 校验
          </Button>
          <Button
            block
            onClick={() => setVariablesDrawerOpen(true)}
            style={{ marginBottom: 8 }}
          >
            {'{ }'} 变量引用
          </Button>
          <Button
            block
            onClick={openVersionDrawer}
            style={{ marginBottom: 8 }}
          >
            🕘 版本历史
          </Button>
          <Button
            type="primary"
            block
            loading={running}
            onClick={handleRun}
            style={{ background: '#52c41a', borderColor: '#52c41a' }}
          >
            ▶ 试运行
          </Button>
        </div>
      </div>

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
          /* ========== 连线样式（与 Coze 对齐） ========== */
          .gedit-flow-line,
          [class*='flow-line'] path {
            stroke: #c0c4cc !important;
            stroke-width: 2 !important;
            fill: none !important;
            transition: stroke 0.15s, stroke-width 0.15s;
          }
          .gedit-flow-line:hover,
          [class*='flow-line']:hover path {
            stroke: #6366f1 !important;
            stroke-width: 2.5 !important;
          }
          .gedit-flow-line.selected,
          .gedit-flow-line.active,
          [class*='flow-line'].selected path,
          [class*='flow-line'].active path {
            stroke: #6366f1 !important;
            stroke-width: 2.5 !important;
            filter: drop-shadow(0 0 3px rgba(99,102,241,0.4));
          }
          /* 端口圆点 */
          .gedit-port,
          [class*='port'] {
            background: #fff !important;
            border: 2px solid #c0c4cc !important;
            transition: border-color 0.15s, transform 0.15s;
          }
          .gedit-port:hover,
          [class*='port']:hover {
            border-color: #6366f1 !important;
            transform: scale(1.3);
          }
          /* 窄屏适配（U-P4）：< 1024px 隐藏左侧节点库 */
          @media (max-width: 1024px) {
            .boxia-left-panel { display: none !important; }
          }
          /* RefChipInput 聚焦态 */
          .boxia-ref-chip-input:focus-within {
            border-color: #6366f1 !important;
            box-shadow: 0 0 0 2px rgba(99,102,241,0.1);
          }
        `}</style>

        {/* 顶部悬浮工具栏 */}
        <CanvasToolbar ctxRef={ctxRef} zoom={canvasZoom} />

        {/* 画布右键菜单（U-P2） */}
        <CanvasContextMenu
          onAddNode={() => { /* 打开左侧节点库 */ }}
          onAutoLayout={() => message.info('自动排版功能待 FlowGram 插件支持')}
          onFitView={() => {
            const ctx = ctxRef.current as any;
            ctx?.viewport?.fitView?.();
          }}
          onDeleteSelected={() => {
            if (selectedNodeId) setDeleteNodeOpen(true);
            else message.info('请先选中一个节点');
          }}
          onCopyNode={() => message.info('复制节点功能待实现')}
          onPasteNode={() => message.info('粘贴节点功能待实现')}
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
              addNode(typeKey);
              setAddNodePopover(null);
            }}
            onClose={() => setAddNodePopover(null)}
          />
        )}

        {/* 小地图（U-B3 简化版） */}
        <MiniMap
          nodes={pickerNodes
            .filter((n) => n.position)
            .map((n) => ({
              id: n.id,
              x: n.position!.x,
              y: n.position!.y,
              color: keyToMeta[n.typeKey]?.color,
            }))}
          onNavigate={(x, y) => {
            const ctx = ctxRef.current as any;
            ctx?.viewport?.scrollTo?.({ x, y });
          }}
        />

        {/* 保存状态 + 发布按钮 */}
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
            style={{ background: '#722ed1', borderColor: '#722ed1' }}
          >
            🚀 发布
          </Button>
        <div style={{
          padding: '4px 12px', borderRadius: 6, background: '#fff',
          boxShadow: '0 2px 8px rgba(0,0,0,0.08)', fontSize: 12,
          color: saveStatus === 'error' ? '#d4380d' : saveStatus === 'saving' ? '#1677ff' : '#52c41a',
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: saveStatus === 'error' ? '#ff4d4f' : saveStatus === 'saving' ? '#1677ff' : '#52c41a',
            animation: saveStatus === 'saving' ? 'boxia-pulse 1.2s ease-in-out infinite' : undefined,
          }} />
          {validating && '校验中…'}
          {!validating && saveStatus === 'saving' && '保存中…'}
          {!validating && saveStatus === 'saved' && lastSavedAt && `已保存 ${lastSavedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`}
          {!validating && saveStatus === 'saved' && !lastSavedAt && '已保存'}
          {!validating && saveStatus === 'error' && <span style={{ cursor: 'pointer' }} onClick={() => scheduleSave()}>保存失败，点击重试</span>}
        </div>
        </div>

        {/* 校验问题面板（B10） */}
        {validationIssues.length > 0 && (
          <div style={{
            position: 'absolute', bottom: 220, left: 16, right: 16, zIndex: 100,
            background: '#fff', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
            padding: 12, maxHeight: 200, overflowY: 'auto',
          }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
              校验问题（{validationIssues.filter((i) => i.severity === 'error').length} 错误，{validationIssues.filter((i) => i.severity === 'warning').length} 警告）
            </div>
            {validationIssues.map((issue, idx) => (
              <div key={idx} style={{
                fontSize: 12, padding: '4px 0',
                color: issue.severity === 'error' ? '#ff4d4f' : '#faad14',
                display: 'flex', gap: 8,
              }}>
                <span>{issue.severity === 'error' ? '●' : '▲'}</span>
                <span>{issue.message}</span>
                {issue.node_id && (
                  <Tag style={{ marginLeft: 'auto', fontSize: 11 }}>{issue.node_id}</Tag>
                )}
              </div>
            ))}
          </div>
        )}

        {/* 试运行日志 */}
        {runLogs.length > 0 && (
          <div style={{
            position: 'absolute', bottom: 16, left: 16, right: 16, zIndex: 100,
            maxHeight: 200, overflowY: 'auto',
            background: 'rgba(0,0,0,0.85)', color: '#d9d9d9',
            borderRadius: 6, padding: 12, fontFamily: 'monospace', fontSize: 12,
          }}>
            {runLogs.map((log, i) => (
              <div key={i} style={{ color: log.level === 'error' ? '#ff4d4f' : '#d9d9d9' }}>
                <span style={{ color: '#666' }}>[{log.time}]</span> {log.text}
              </div>
            ))}
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
          selectBox={{ enabled: true }}
          onLoad={(ctx) => {
            ctxRef.current = ctx;
            const doc = ctx.document as any;
            if (doc?.nodes) setNodeCount(doc.nodes.length || 0);
            refreshPickerNodes();
          }}
          onContentChange={() => {
            scheduleSave();
            const ctx = ctxRef.current as any;
            const doc = ctx?.document;
            if (doc?.nodes) setNodeCount(doc.nodes.length || 0);
            refreshPickerNodes();
          }}
          canAddLine={canAddLine}
          canDeleteLine={() => true}
          canDeleteNode={(ctx, node) => {
            // start 节点不允许删除
            if (node.id.startsWith('start-')) {
              message.warning('开始节点不允许删除');
              return false;
            }
            return true;
          }}
          onDragLineEnd={async (ctx: any, params: any) => {
            // 拖线到空白处（没有 toPort）时弹出节点选择面板
            if (!params?.toPort && params?.startPosition) {
              const pos = params.startPosition;
              // 转换为屏幕坐标
              const playground = document.querySelector('.gedit-playground-container');
              if (playground) {
                const rect = playground.getBoundingClientRect();
                setAddNodePopover({
                  x: rect.left + pos.x,
                  y: rect.top + pos.y,
                });
              }
            }
          }}
        />

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
        title={`配置节点 - ${selectedNodeMeta?.title || ''}`}
        open={!!selectedNodeId}
        onClose={() => setSelectedNodeId(null)}
        width={420}
        extra={
          selectedNodeId && selectedNodeMeta?.type_key !== 'start' ? (
            <Button danger size="small" onClick={() => setDeleteNodeOpen(true)}>
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
          />
        )}
        <div style={{ marginTop: 16 }}>
          <Tag color="blue">节点 ID：{selectedNodeId}</Tag>
        </div>
      </Drawer>

      {/* 删除节点确认弹窗（U-S3） */}
      <Modal
        title="删除节点"
        open={deleteNodeOpen}
        onOk={confirmDeleteNode}
        onCancel={() => setDeleteNodeOpen(false)}
        okText="删除"
        okButtonProps={{ danger: true }}
        cancelText="取消"
      >
        <div>
          确定要删除节点 <Tag color="blue">{selectedNodeMeta?.title || selectedNodeId}</Tag> 吗？
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
        width={480}
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
        width={480}
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

// ========== 格式适配 ==========
const SUBGRAPH_NODE_TYPES = new Set(['loop', 'batch', 'subworkflow']);

function toCozeIR(
  flowgram: WorkflowJSON,
  keyToCozeType: Record<string, string>,
): Record<string, unknown> {
  const nodes = (flowgram.nodes || []).map((n) => {
    const cozeType = keyToCozeType[n.type as string] || n.type;
    const data = (n.data || {}) as Record<string, unknown>;
    const config = ((data.config || {}) as Record<string, unknown>);
    const out: Record<string, unknown> = {
      id: n.id,
      type: cozeType,
      meta: { position: (n.meta as { position?: { x: number; y: number } })?.position ?? { x: 0, y: 0 } },
      data: {
        nodeMeta: { title: data.title || '' },
        inputs: {
          inputParameters: ((config.inputParameters || []) as Array<{ name: string; input: unknown }>),
          ...config,
        },
        outputs: (data.outputs || []) as unknown[],
      },
    };
    // 子图节点：把 node.data.subgraph (WorkflowJSON) 转成 blocks/edges
    if (SUBGRAPH_NODE_TYPES.has(String(n.type)) && data.subgraph) {
      const sub = data.subgraph as WorkflowJSON;
      const nested = toCozeIR(sub, keyToCozeType);
      out.blocks = nested.nodes;
      out.edges = nested.edges;
    }
    return out;
  });

  const edges = (flowgram.edges || []).map((e) => {
    const edge = e as unknown as Record<string, unknown>;
    return {
      id: (edge.id as string) || `edge-${Math.random().toString(36).slice(2, 8)}`,
      sourceNodeID: edge.source,
      targetNodeID: edge.target,
      sourcePortID: edge.sourcePortID,
      targetPortID: edge.targetPortID,
    };
  });

  return { nodes, edges };
}

function fromCozeIR(
  coze: unknown,
  cozeTypeToKey: Record<string, string>,
): WorkflowJSON {
  if (!coze || typeof coze !== 'object') return DEFAULT_GRAPH;
  const raw = coze as { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> };
  if (!Array.isArray(raw.nodes) || raw.nodes.length === 0) return DEFAULT_GRAPH;

  const nodes = raw.nodes.map((n) => {
    const cozeType = String(n.type ?? '');
    const registryType = cozeTypeToKey[cozeType] || String(n.type || 'default');
    const data = (n.data || {}) as Record<string, unknown>;
    const nodeMeta = (data.nodeMeta || {}) as { title?: string };
    const inputs = (data.inputs || {}) as Record<string, unknown>;
    const out: WorkflowJSON['nodes'][number] = {
      id: String(n.id),
      type: registryType,
      meta: {
        position: (n.meta as { position?: { x: number; y: number } })?.position ?? { x: 0, y: 0 },
      },
      data: {
        title: nodeMeta.title,
        config: inputs,
        outputs: (data.outputs || []) as unknown[],
      },
    } as WorkflowJSON['nodes'][number];
    // 子图节点：blocks/edges 还原成 node.data.subgraph
    const blocks = Array.isArray(n.blocks) ? n.blocks as Array<Record<string, unknown>> : [];
    const innerEdges = Array.isArray(n.edges) ? n.edges as Array<Record<string, unknown>> : [];
    if (blocks.length > 0) {
      const subCoze = { nodes: blocks, edges: innerEdges };
      (out.data as Record<string, unknown>).subgraph = fromCozeIR(subCoze, cozeTypeToKey);
    }
    return out;
  });

  const edges = (raw.edges || []).map((e) => ({
    id: String(e.id ?? `edge-${Math.random().toString(36).slice(2, 8)}`),
    source: e.sourceNodeID,
    target: e.targetNodeID,
    sourcePortID: e.sourcePortID,
    targetPortID: e.targetPortID,
  })) as unknown as WorkflowJSON['edges'];

  return { nodes, edges };
}
