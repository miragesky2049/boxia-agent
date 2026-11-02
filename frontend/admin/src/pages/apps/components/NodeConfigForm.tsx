import { useEffect, useMemo, useState } from 'react';
import {
  AutoComplete, Button, Input, Popover, Select, Space, Tag, Tooltip, Tree, Typography,
} from 'antd';
import type { TreeProps } from 'antd';
import { listAvailableModels, type ModelCatalogItem } from '../../../api/models';
import type { DatasetItem } from '../../../api/datasets';
import type { NodeMeta } from '../../../api/nodeMeta';
import type { FlowType } from '../../../api/apps';
import { hasOutputs } from '../canvas/metadata/capabilities';
import { isNodeAvailable } from '../canvas/metadata/flowCapabilities';
import { FieldControl } from '../canvas/fields/fieldControls';
import { ToolListEditor } from './ToolListEditor';
import { groupConfigFields } from './configSections';
import { getNextRecommendations } from './nodeNextRecommendations';

export type NodeConfigValues = Record<string, any>;

export interface GraphNodeSummary {
  id: string;
  typeKey: string;
  title: string;
  config: Record<string, any>;
  position?: { x: number; y: number };
}

// 抽屉「输入」区：按入边反查上游节点可引用字段
export interface UpstreamInputGroup {
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

// ========== IF case 可视化编辑器（T7） ==========
export interface CaseItem {
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

export function parseCasesValue(raw: any): CaseItem[] {
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
    // 条件节点至少保留一个「如果」，否则卡片与抽屉只剩「否则」
    if (cases.length <= 1) return;
    onChange(cases.filter((_, i) => i !== idx));
  };

  const addCase = () => {
    // 删除中间条件后再新增，直接用 length+1 会和已有 case_id 冲突
    const used = new Set(cases.map((c) => c.case_id));
    let n = cases.length + 1;
    while (used.has(`case_${n}`)) n += 1;
    onChange([...cases, { case_id: `case_${n}`, left: '', operator: 'eq', right: '' }]);
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
              disabled={cases.length <= 1}
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

// ========== 意图列表编辑器（意图识别节点） ==========
export interface IntentItem {
  id: number;
  name: string;
  description: string;
}

export function parseIntentsValue(raw: any): IntentItem[] {
  if (!Array.isArray(raw)) return [];
  const items: IntentItem[] = [];
  raw.forEach((item, idx) => {
    const name = typeof item === 'string'
      ? item.trim()
      : String(item?.name ?? item?.intent ?? '').trim();
    if (!name) return;
    const parsedId = Number(item?.id);
    items.push({
      id: Number.isFinite(parsedId) && parsedId > 0 ? parsedId : idx + 1,
      name,
      description: typeof item === 'object' && item ? String(item.description ?? '') : '',
    });
  });
  return items;
}

function IntentListEditor({
  value,
  onChange,
}: {
  value: any;
  onChange: (next: IntentItem[]) => void;
}) {
  const items = useMemo(() => parseIntentsValue(value), [value]);

  const updateItem = (idx: number, patch: Partial<IntentItem>) => {
    onChange(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const removeItem = (idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    const nextId = items.reduce((max, it) => Math.max(max, it.id), 0) + 1;
    onChange([...items, { id: nextId, name: '', description: '' }]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.length === 0 && (
        <div style={{ fontSize: 12, color: '#999' }}>暂无意图，点击下方按钮添加</div>
      )}
      {items.map((it, idx) => (
        <div
          key={it.id}
          style={{
            padding: 8,
            background: '#fafafa',
            borderRadius: 6,
            border: '1px solid #f0f0f0',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
          }}
        >
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: '#9ca3af', width: 46 }}>出口 {idx + 1}</span>
            <Input
              size="small"
              style={{ width: 150 }}
              placeholder="意图名称"
              value={it.name}
              onChange={(e) => updateItem(idx, { name: e.target.value })}
            />
            <Input
              size="small"
              style={{ flex: 1 }}
              placeholder="意图描述（帮助模型判断）"
              value={it.description}
              onChange={(e) => updateItem(idx, { description: e.target.value })}
            />
            <Button
              size="small"
              type="text"
              danger
              onClick={() => removeItem(idx)}
              aria-label="删除意图"
            >
              删除
            </Button>
          </div>
        </div>
      ))}
      <div style={{
        padding: '6px 8px', background: '#f9fafb', borderRadius: 6,
        fontSize: 12, color: '#9ca3af',
      }}>
        其他（未命中任何意图时的兜底出口）
      </div>
      <Button size="small" onClick={addItem} style={{ alignSelf: 'flex-start' }} type="dashed">
        + 添加意图
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
    if (key.includes(k)) return PROVIDER_COLORS[k] ?? '#6b7280';
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
export function TraceEntry({ entry }: { entry: { type: string; payload: Record<string, any> } }) {
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
export type OutputFieldItem = {
  name: string;
  type: string;
  description?: string;
};

const OUTPUT_TYPE_OPTIONS = [
  'string', 'number', 'boolean', 'object', 'array',
  'array[string]', 'array[number]', 'array[object]',
];

export function parseOutputsValue(raw: any): OutputFieldItem[] {
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

export function NodeConfigForm({
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
  flowType,
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
  flowType?: FlowType;
}) {
  const handleFieldChange = (name: string, value: any) => {
    onChange({ [name]: value });
  };

  // 推荐下游节点按当前流程形态过滤，避免工作流里出现对话流专属节点
  const nextRecommendations = useMemo(
    () => getNextRecommendations(nodeMeta.type_key, keyToMeta)
      .filter((rec) => !flowType || isNodeAvailable(rec.typeKey, flowType)),
    [nodeMeta.type_key, keyToMeta, flowType],
  );

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
                ) : field.field_type === 'intent_list' ? (
                  <IntentListEditor
                    value={values[field.name]}
                    onChange={(next) => handleFieldChange(field.name, next)}
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
      {onAddNext && nextRecommendations.length > 0 && (
        <div style={{
          marginTop: 12, paddingTop: 12, borderTop: '1px solid #f0f0f0',
        }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 8,
          }}>
            下一步
          </div>
          <Space direction="vertical" style={{ width: '100%' }} size={6}>
            {nextRecommendations.map((rec) => {
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
