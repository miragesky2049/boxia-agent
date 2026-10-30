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
import { useCallback, useEffect, useRef, useState } from 'react';
import { Drawer, Input, Button, Select, Tag, Space, Typography, InputNumber, Divider, message } from 'antd';
import { getAppGraph, saveAppGraph, debugRunAppStream } from '../../api/apps';
import { ApiError } from '../../api/client';

// ========== 节点类型定义 ==========
type NodeTypeKey = 'start' | 'end' | 'llm' | 'http' | 'if_else';

interface NodeTypeMeta {
  type: string;
  cozeType: string;
  title: string;
  color: string;
  width: number;
  defaultPorts: Array<{ type: 'input' | 'output' }>;
}

const NODE_TYPES: Record<NodeTypeKey, NodeTypeMeta> = {
  start:   { type: 'start',   cozeType: '1',  title: '开始', color: '#1677ff', width: 100, defaultPorts: [{ type: 'output' }] },
  end:     { type: 'end',     cozeType: '2',  title: '结束', color: '#52c41a', width: 100, defaultPorts: [{ type: 'input' }] },
  llm:     { type: 'llm',     cozeType: '3',  title: '大模型', color: '#722ed1', width: 160, defaultPorts: [{ type: 'input' }, { type: 'output' }] },
  http:    { type: 'http',    cozeType: '45', title: 'HTTP 请求', color: '#fa8c16', width: 160, defaultPorts: [{ type: 'input' }, { type: 'output' }] },
  if_else: { type: 'if_else', cozeType: '8',  title: '条件分支', color: '#eb2f96', width: 160, defaultPorts: [{ type: 'input' }, { type: 'output' }] },
};

const NODE_TYPE_BY_REGISTRY: Record<string, NodeTypeMeta> = Object.fromEntries(
  Object.values(NODE_TYPES).map((m) => [m.type, m]),
);

// ========== 运行时节点状态（用于高亮） ==========
type RunNodeStatus = 'running' | 'success' | 'error';

// ========== 节点渲染组件（双击打开配置） ==========
function makeNodeRenderer(
  meta: NodeTypeMeta,
  _ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>,
  onNodeDoubleClick: (node: WorkflowNodeEntity) => void,
) {
  return function NodeRenderer({ node }: { node: WorkflowNodeEntity }) {
    const title = (node.data as { title?: string })?.title || meta.title;
    return (
      <WorkflowNodeRenderer node={node}>
        <div
          onDoubleClick={() => onNodeDoubleClick(node)}
          style={{
            padding: '12px 20px',
            background: meta.color,
            color: '#fff',
            borderRadius: 8,
            fontSize: 14,
            fontWeight: 500,
            textAlign: 'center',
            minWidth: meta.width - 40,
            cursor: 'pointer',
            userSelect: 'none',
          }}
        >
          {title}
        </div>
      </WorkflowNodeRenderer>
    );
  };
}

const nodeRegistries: WorkflowNodeRegistry[] = Object.values(NODE_TYPES).map((meta) => ({
  type: meta.type,
  meta: {
    defaultPorts: meta.defaultPorts,
    size: { width: meta.width, height: 40 },
    renderKey: meta.type,
  },
}));

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

// ========== 格式适配 ==========
function toCozeIR(flowgram: WorkflowJSON): Record<string, unknown> {
  const nodes = (flowgram.nodes || []).map((n) => {
    const meta = NODE_TYPE_BY_REGISTRY[n.type as string];
    const cozeType = meta?.cozeType ?? n.type;
    const data = (n.data || {}) as Record<string, unknown>;
    const config = ((data.config || {}) as Record<string, unknown>);
    return {
      id: n.id,
      type: cozeType,
      meta: { position: (n.meta as { position?: { x: number; y: number } })?.position ?? { x: 0, y: 0 } },
      data: {
        nodeMeta: { title: data.title || meta?.title || '' },
        inputs: {
          inputParameters: ((config.inputParameters || []) as Array<{ name: string; input: unknown }>),
          ...config,
        },
        outputs: (data.outputs || []) as unknown[],
      },
    };
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

function fromCozeIR(coze: unknown): WorkflowJSON {
  if (!coze || typeof coze !== 'object') return DEFAULT_GRAPH;
  const raw = coze as { nodes?: Array<Record<string, unknown>>; edges?: Array<Record<string, unknown>> };
  if (!Array.isArray(raw.nodes) || raw.nodes.length === 0) return DEFAULT_GRAPH;

  const cozeToRegistry: Record<string, string> = Object.fromEntries(
    Object.values(NODE_TYPES).map((m) => [m.cozeType, m.type]),
  );

  const nodes = raw.nodes.map((n) => {
    const cozeType = String(n.type ?? '');
    const registryType = cozeToRegistry[cozeType] || String(n.type || 'default');
    const data = (n.data || {}) as Record<string, unknown>;
    const nodeMeta = (data.nodeMeta || {}) as { title?: string };
    const inputs = (data.inputs || {}) as Record<string, unknown>;
    return {
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
  });

  const edges = (raw.edges || []).map((e) => ({
    id: String(e.id ?? `edge-${Math.random().toString(36).slice(2, 8)}`),
    source: e.sourceNodeID,
    target: e.targetNodeID,
    sourcePortID: e.sourcePortID,
    targetPortID: e.targetPortID,
  })) as WorkflowJSON['edges'];

  return { nodes, edges };
}

// ========== 节点配置表单 ==========
interface NodeConfigValues {
  title?: string;
  // LLM
  modelName?: string;
  prompt?: string;
  temperature?: number;
  maxTokens?: number;
  // HTTP
  url?: string;
  method?: string;
  headers?: string;
  body?: string;
  // if_else
  condition?: string;
}

function NodeConfigForm({
  nodeType,
  values,
  onChange,
}: {
  nodeType: NodeTypeKey;
  values: NodeConfigValues;
  onChange: (patch: Partial<NodeConfigValues>) => void;
}) {
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

      {nodeType === 'llm' && (
        <>
          <Divider style={{ margin: '4px 0' }} orientation="left" orientationMargin={0}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>模型</Typography.Text>
          </Divider>
          <div>
            <Typography.Text type="secondary">模型名称</Typography.Text>
            <Input
              value={values.modelName}
              onChange={(e) => onChange({ modelName: e.target.value })}
              placeholder="如：gpt-4o / qwen-max"
            />
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <Typography.Text type="secondary">Temperature</Typography.Text>
              <InputNumber
                value={values.temperature ?? 0.7}
                min={0}
                max={2}
                step={0.1}
                onChange={(v) => onChange({ temperature: v ?? 0.7 })}
                style={{ width: '100%' }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <Typography.Text type="secondary">最大 Token</Typography.Text>
              <InputNumber
                value={values.maxTokens ?? 2048}
                min={1}
                max={128000}
                onChange={(v) => onChange({ maxTokens: v ?? 2048 })}
                style={{ width: '100%' }}
              />
            </div>
          </div>
          <div>
            <Typography.Text type="secondary">系统 Prompt</Typography.Text>
            <Input.TextArea
              rows={6}
              value={values.prompt}
              onChange={(e) => onChange({ prompt: e.target.value })}
              placeholder="你是一个助手..."
            />
          </div>
        </>
      )}

      {nodeType === 'http' && (
        <>
          <Divider style={{ margin: '4px 0' }} orientation="left" orientationMargin={0}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>请求</Typography.Text>
          </Divider>
          <div>
            <Typography.Text type="secondary">URL</Typography.Text>
            <Input
              value={values.url}
              onChange={(e) => onChange({ url: e.target.value })}
              placeholder="https://api.example.com/endpoint"
            />
          </div>
          <div>
            <Typography.Text type="secondary">方法</Typography.Text>
            <Select
              value={values.method || 'GET'}
              onChange={(v) => onChange({ method: v })}
              options={['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map((m) => ({ value: m, label: m }))}
              style={{ width: '100%' }}
            />
          </div>
          <div>
            <Typography.Text type="secondary">请求头（JSON）</Typography.Text>
            <Input.TextArea
              rows={3}
              value={values.headers}
              onChange={(e) => onChange({ headers: e.target.value })}
              placeholder={'{"Content-Type": "application/json"}'}
            />
          </div>
          <div>
            <Typography.Text type="secondary">请求体</Typography.Text>
            <Input.TextArea
              rows={4}
              value={values.body}
              onChange={(e) => onChange({ body: e.target.value })}
              placeholder={'{\n  "key": "value"\n}'}
            />
          </div>
        </>
      )}

      {nodeType === 'if_else' && (
        <div>
          <Divider style={{ margin: '4px 0' }} orientation="left" orientationMargin={0}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>条件</Typography.Text>
          </Divider>
          <Typography.Text type="secondary">条件表达式</Typography.Text>
          <Input.TextArea
            rows={3}
            value={values.condition}
            onChange={(e) => onChange({ condition: e.target.value })}
            placeholder="如：{{start.output.user_id}} == 'admin'"
          />
        </div>
      )}
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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedNodeType, setSelectedNodeType] = useState<NodeTypeKey>('llm');
  const [configValues, setConfigValues] = useState<NodeConfigValues>({});
  const [running, setRunning] = useState(false);
  const [runLogs, setRunLogs] = useState<Array<{ time: string; text: string; level?: 'info' | 'error' }>>([]);
  const ctxRef = useRef<FreeLayoutPluginContext | null>(null);
  const saveTimerRef = useRef<number | null>(null);
  const nodeCounterRef = useRef<Record<string, number>>({});

  // ========== 加载图 ==========
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        try {
          const resp = await getAppGraph(id);
          if (cancelled) return;
          setInitialData(fromCozeIR(resp.graph));
        } catch (err) {
          if (err instanceof ApiError && err.status === 404) {
            if (!cancelled) setInitialData(DEFAULT_GRAPH);
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
  }, [id]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    };
  }, []);

  // ========== 保存 ==========
  const scheduleSave = useCallback(() => {
    if (!ctxRef.current || !id) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    setSaveStatus('saving');
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        const flowgram = ctxRef.current!.document.toJSON() as unknown as WorkflowJSON;
        const cozeIR = toCozeIR(flowgram);
        await saveAppGraph(id, cozeIR as never);
        setSaveStatus('saved');
      } catch {
        setSaveStatus('error');
      }
    }, 800);
  }, [id]);

  // ========== 添加节点 ==========
  const addNode = useCallback((typeKey: NodeTypeKey) => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    const meta = NODE_TYPES[typeKey];
    nodeCounterRef.current[typeKey] = (nodeCounterRef.current[typeKey] ?? 0) + 1;
    const nodeId = `${typeKey}-${Date.now().toString(36)}-${nodeCounterRef.current[typeKey]}`;
    const offsetX = 120 + Math.random() * 200;
    const offsetY = 100 + Math.random() * 150;
    const root = ctx.document.getNode('root');
    ctx.document.addNode({
      id: nodeId,
      type: meta.type,
      meta: { position: { x: 300 + offsetX, y: 200 + offsetY } },
      data: { title: meta.title, config: {} },
      parent: root,
    });
  }, []);

  // ========== 双击节点打开配置 ==========
  const handleNodeDoubleClick = useCallback((node: WorkflowNodeEntity) => {
    setSelectedNodeId(node.id);
    // node.id 形如 `${typeKey}-...`，直接从前缀取类型
    const prefix = node.id.split('-')[0] as NodeTypeKey;
    const found = (Object.keys(NODE_TYPES) as NodeTypeKey[]).includes(prefix) ? prefix : 'llm';
    setSelectedNodeType(found);
    const data = (node.data || {}) as { title?: string; config?: NodeConfigValues };
    setConfigValues({
      title: data.title,
      ...(data.config || {}),
    });
  }, []);

  const renderNodes = Object.fromEntries(
    Object.values(NODE_TYPES).map((meta) => [
      meta.type,
      makeNodeRenderer(meta, ctxRef, handleNodeDoubleClick),
    ]),
  ) as Record<string, React.ComponentType<{ node: WorkflowNodeEntity }>>;

  // ========== 抽屉配置变更 ==========
  const handleConfigChange = useCallback((patch: Partial<NodeConfigValues>) => {
    setConfigValues((prev) => {
      const next = { ...prev, ...patch };
      const ctx = ctxRef.current;
      if (ctx && selectedNodeId) {
        const node = ctx.document.getNode(selectedNodeId);
        if (node) {
          node.data = {
            ...(node.data as Record<string, unknown>),
            title: next.title,
            config: next,
          };
        }
      }
      return next;
    });
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
    running: '0 0 0 4px rgba(24,144,255,0.35)',
    success: '0 0 0 4px rgba(82,196,26,0.35)',
    error: '0 0 0 4px rgba(255,77,79,0.35)',
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
  const handleRun = useCallback(async () => {
    if (!id || running) return;
    setRunning(true);
    setRunLogs([]);
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
        graph = toCozeIR(flowgram);
      } else {
        graph = {};
      }
      appendLog('启动试运行...');
      await debugRunAppStream(
        { graph: graph as never, inputs: {} },
        (event) => {
          if (event.event === 'node_start') {
            const nodeId = String(event.data.node_id || '');
            if (nodeId) setNodeRunStatus(nodeId, 'running');
            appendLog(`→ 开始节点 ${nodeId} (${event.data.node_type})`);
          } else if (event.event === 'node_end') {
            const nodeId = String(event.data.node_id || '');
            const status = event.data.status === 'error' ? 'error' : 'success';
            if (nodeId) setNodeRunStatus(nodeId, status as RunNodeStatus);
            appendLog(`← 完成节点 ${nodeId}：${event.data.status}`, status as 'info' | 'error');
          } else if (event.event === 'result') {
            appendLog(`✓ 运行完成：${JSON.stringify(event.data.output || {})}`);
          } else if (event.event === 'error') {
            appendLog(`✗ 错误：${event.data.message || event.data.error}`, 'error');
          }
        },
      );
      appendLog('试运行结束');
    } catch (err) {
      appendLog(`试运行失败：${err instanceof Error ? err.message : String(err)}`, 'error');
    } finally {
      setRunning(false);
    }
  }, [id, running, clearAllRunStatus, setNodeRunStatus]);

  // ========== 渲染 ==========
  if (!id) return <div style={{ padding: 24 }}>缺少应用 ID</div>;
  if (loadError) return <div style={{ padding: 24, color: '#d4380d' }}>加载失败：{loadError}</div>;
  if (!initialData) return <div style={{ padding: 24 }}>加载中…</div>;

  return (
    <div style={{ display: 'flex', width: '100%', height: 'calc(100vh - 108px)' }}>
      {/* 左侧节点面板 */}
      <div style={{
        width: 180, padding: 12, background: '#fafafa',
        borderRight: '1px solid #f0f0f0',
        display: 'flex', flexDirection: 'column', gap: 8, overflowY: 'auto',
      }}>
        <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>节点库</div>
        {(Object.keys(NODE_TYPES) as NodeTypeKey[]).map((key) => {
          const meta = NODE_TYPES[key];
          return (
            <button
              key={key}
              onClick={() => addNode(key)}
              disabled={key === 'start'}
              style={{
                padding: '8px 12px', background: '#fff',
                border: '1px solid #d9d9d9', borderRadius: 6,
                cursor: key === 'start' ? 'not-allowed' : 'pointer',
                fontSize: 13, color: meta.color, textAlign: 'left',
                opacity: key === 'start' ? 0.5 : 1,
              }}
            >
              <span style={{
                display: 'inline-block', width: 8, height: 8,
                borderRadius: '50%', background: meta.color, marginRight: 8,
              }} />
              {meta.title}
            </button>
          );
        })}

        <div style={{ marginTop: 'auto', paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
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
            0%, 100% { box-shadow: 0 0 0 4px rgba(24,144,255,0.35); }
            50% { box-shadow: 0 0 0 8px rgba(24,144,255,0.15); }
          }
          .boxia-node-running {
            animation: boxia-pulse 1.2s ease-in-out infinite;
          }
        `}</style>

        {/* 保存状态 */}
        <div style={{
          position: 'absolute', top: 8, right: 16, zIndex: 100,
          padding: '4px 12px', borderRadius: 6, background: '#fff',
          boxShadow: '0 2px 8px rgba(0,0,0,0.08)', fontSize: 12,
          color: saveStatus === 'error' ? '#d4380d' : '#52c41a',
        }}>
          {saveStatus === 'saving' && '保存中…'}
          {saveStatus === 'saved' && '已保存'}
          {saveStatus === 'error' && '保存失败'}
        </div>

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

        <FreeLayoutEditor
          nodeRegistries={nodeRegistries}
          materials={{ renderNodes }}
          initialData={initialData}
          onLoad={(ctx) => { ctxRef.current = ctx; }}
          onContentChange={() => { scheduleSave(); }}
          canAddLine={canAddLine}
        />
      </div>

      {/* 节点配置抽屉 */}
      <Drawer
        title={`配置节点 - ${NODE_TYPES[selectedNodeType]?.title || ''}`}
        open={!!selectedNodeId}
        onClose={() => setSelectedNodeId(null)}
        width={420}
      >
        <NodeConfigForm
          nodeType={selectedNodeType}
          values={configValues}
          onChange={handleConfigChange}
        />
        <div style={{ marginTop: 16 }}>
          <Tag color="blue">节点 ID：{selectedNodeId}</Tag>
        </div>
      </Drawer>
    </div>
  );
}
