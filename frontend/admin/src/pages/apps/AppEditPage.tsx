import { FreeLayoutEditor } from '@flowgram.ai/free-layout-editor';
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
import { Button, message } from 'antd';
import { getAppGraph, saveAppGraph, debugRunAppStream, debugRunAppStreamResume, debugRunNode, validateGraph, listGraphVersions, rollbackGraph, publishGraph, type GraphValidationIssue, type GraphVersionItem, type ApprovalInterruptPayload, type NodeDebugRunResult } from '../../api/apps';
import { ApiError } from '../../api/client';
import { getNodeMeta, type NodeMeta } from '../../api/nodeMeta';
import { listDatasets, type DatasetItem } from '../../api/datasets';
import { makeNodeRenderer, type NodeCardActions } from './components/nodeRenderer';
import { CanvasToolbar } from './components/CanvasToolbar';
import { ResourceSidebar } from './components/ResourceSidebar';
import { EmptyCanvasWelcome } from './components/EmptyCanvasWelcome';
import { VariablesDrawer } from './components/VariablesDrawer';
import { usePortTooltips } from './components/usePortTooltips';
import { CanvasContextMenu } from './components/CanvasContextMenu';
import { ConversationDrawer } from './components/ConversationDrawer';
import { AddNodePopover } from './components/AddNodePopover';
import { MiniMap } from './components/MiniMap';
import { canCopy, canDelete, hasSubgraph } from './canvas/metadata/capabilities';
import { AlignGuides } from './components/AlignGuides';
import { CanvasStyles } from './components/CanvasStyles';
import { BottomStatusPanel } from './components/BottomStatusPanel';
import { NodeDebugPanel } from './components/NodeDebugPanel';
import { NodeConfigDrawer } from './components/NodeConfigDrawer';
import { RenameNodeModal, DeleteNodeModal } from './components/NodeActionModals';
import { RunInputsModal } from './components/RunInputsModal';
import { VersionHistoryDrawer } from './components/VersionHistoryDrawer';
import { ApprovalDrawer } from './components/ApprovalDrawer';
import { SaveStatusBar, PublishBar, type SaveStatus } from './components/CanvasHeaderStatus';
import { SubgraphBreadcrumb } from './components/SubgraphBreadcrumb';
import {
  parseOutputsValue,
  type NodeConfigValues,
  type GraphNodeSummary,
  type UpstreamInputGroup,
  type OutputFieldItem,
} from './components/NodeConfigForm';
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
  getZoom,
  removeNode,
  redo,
  scrollToCanvasPoint,
  selectAllNodes,
  setScroll,
  setZoom,
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
import { downloadBlob, exportElementAsPng } from './canvas/exportImage';
import { setupCanvasPan } from './canvas/adapters/canvasPan';

// ========== 运行时节点状态（用于高亮） ==========
type RunNodeStatus = 'running' | 'success' | 'error';



// 单节点试运行只带字面量入参；引用值等由后端按空上游求值，不阻断运行
function collectDebugInputs(config: Record<string, any>): Record<string, unknown> {
  const params = Array.isArray(config?.inputParameters) ? config.inputParameters : [];
  const result: Record<string, unknown> = {};
  for (const param of params) {
    if (!param || typeof param !== 'object' || !param.name) continue;
    const value = param.input?.value;
    if (value?.type === 'literal') result[param.name] = value.content;
  }
  return result;
}



// ========== 页面组件 ==========

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
  const [nodeDebugRunning, setNodeDebugRunning] = useState(false);
  const [nodeDebugResult, setNodeDebugResult] = useState<NodeDebugRunResult | null>(null);
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
  const [conversationDrawerOpen, setConversationDrawerOpen] = useState(false);
  const [addNodePopover, setAddNodePopover] = useState<{ x: number; y: number; fromNodeId?: string } | null>(null);
  const [datasetOptions, setDatasetOptions] = useState<DatasetItem[]>([]);
  // V4：左侧资源树折叠状态
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // 窄屏下手动展开后，本次会话不再被断点监听强制折叠
  const manualSidebarExpandRef = useRef(false);
  // V1/V2：右下角校验/日志合并面板
  const [panelOpen, setPanelOpen] = useState(false);
  const [exportingPng, setExportingPng] = useState(false);
  const [panelTab, setPanelTab] = useState<'validation' | 'logs' | 'history'>('logs');
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
    downloadBlob(
      new Blob([JSON.stringify(ir, null, 2)], { type: 'application/json' }),
      `${id || 'workflow'}.json`,
    );
    message.success('已导出工作流 JSON');
  }, [keyToCozeType, id]);

  // N9-06：导出画布 PNG（full = 适应视图后整图，viewport = 当前视口）
  const handleExportPng = useCallback(async (mode: 'full' | 'viewport') => {
    const ctx = ctxRef.current;
    const playground = document.querySelector<HTMLElement>('.gedit-playground-container');
    if (!ctx || !playground) {
      message.error('画布未就绪，无法导出');
      return;
    }
    setExportingPng(true);
    const prevZoom = getZoom(ctx);
    const prevScroll = getScroll(ctx);
    try {
      if (mode === 'full') {
        await fitView(ctx, false);
        // 等两帧，确保视口变换与节点位置已落定再截图
        await new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        });
      }
      await exportElementAsPng(playground, `${id || 'workflow'}-${mode === 'full' ? 'full' : 'view'}.png`);
      message.success('已导出画布 PNG');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '导出 PNG 失败');
    } finally {
      if (mode === 'full') {
        setScroll(ctx, prevScroll.x, prevScroll.y);
        setZoom(ctx, prevZoom);
      }
      setExportingPng(false);
    }
  }, [id]);
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
    const allNodes = (docJson.nodes || []) as Array<{ id: string; type?: string; meta?: { position?: { x: number; y: number } } }>;

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
    setNodeDebugResult(null);
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
    // document.toJSON 的边字段是 sourceNodeID/targetNodeID
    const edges = ((json?.edges || []) as unknown as Array<{ sourceNodeID?: string; targetNodeID?: string }>);
    const groups: UpstreamInputGroup[] = [];
    for (const edge of edges) {
      if (String(edge.targetNodeID) !== node.id) continue;
      const srcId = String(edge.sourceNodeID || '');
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
    _silent?: boolean,
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

  // 单节点试运行（N9-03）：只跑当前节点，不写运行历史、不改变画布状态
  const handleDebugNode = useCallback(async () => {
    const ctx = ctxRef.current;
    if (!ctx || !selectedNodeId || nodeDebugRunning) return;
    const flowgram = toWorkflowJSON(ctx);
    const graph = toCozeIR(flowgram, keyToCozeType, graphSchemaVersionRef.current);
    setNodeDebugRunning(true);
    setNodeDebugResult(null);
    try {
      const result = await debugRunNode({
        graph: graph as never,
        node_id: selectedNodeId,
        inputs: collectDebugInputs(configValues),
      });
      setNodeDebugResult(result);
      if (result.status === 'error') message.error(result.error || '节点试运行失败');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '节点试运行失败');
    } finally {
      setNodeDebugRunning(false);
    }
  }, [selectedNodeId, nodeDebugRunning, keyToCozeType, configValues]);

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
        if (renameTarget || deleteNodeOpen || versionDrawerOpen || variablesDrawerOpen
          || conversationDrawerOpen || approvalState.open) {
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
    renameTarget, deleteNodeOpen, versionDrawerOpen, variablesDrawerOpen,
    conversationDrawerOpen, approvalState.open,
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
        onOpenConversation={() => setConversationDrawerOpen(true)}
      />

      {/* 画布区域 */}
      <div style={{ flex: 1, position: 'relative' }}>
        <CanvasStyles />

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
          onExportPng={(mode) => { void handleExportPng(mode); }}
          exportingPng={exportingPng}
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

        <SaveStatusBar
          saveStatus={saveStatus}
          lastSavedAt={lastSavedAt}
          validating={validating}
          validationIssues={validationIssues}
          onRetry={() => scheduleSave()}
          onOpenValidation={() => {
            void doValidate().then(() => {
              setPanelTab('validation');
              setPanelOpen(true);
            });
          }}
          onOpenHistory={() => {
            setPanelTab('history');
            setPanelOpen(true);
          }}
        />

        <PublishBar
          publishedVersion={publishedVersion}
          publishing={publishing}
          onPublish={handlePublish}
        />

        {/* 校验问题 + 运行日志 合并面板（V1/V2）：右下角可折叠 Tab 抽屉 */}
        <BottomStatusPanel
          applicationId={id}
          open={panelOpen}
          tab={panelTab}
          validationIssues={validationIssues}
          runLogs={runLogs}
          onTabChange={setPanelTab}
          onClose={() => setPanelOpen(false)}
        />

        <SubgraphBreadcrumb
          stackDepth={subgraphStack.length}
          breadcrumb={subgraphBreadcrumb}
          onExit={exitSubgraph}
        />

        <FreeLayoutEditor
          key={editorKey}
          nodeRegistries={nodeRegistries}
          materials={{ renderNodes: renderNodes as any }}
          initialData={initialData}
          // T9-07：对齐 Coze —— 普通左键拖拽平移（下方自绘），Shift+拖拽才框选
          selectBox={{ enable: true, canSelect: (e) => e.shiftKey }}
          // T9-07：撤销/重做依赖 history 插件，未开启时 ctx.history 取值会抛异常
          history={{ enable: true }}
          onLoad={(ctx) => {
            ctxRef.current = ctx;
            (window as any).__flowCtx = ctx;
            // history 选项类型只暴露 enable/onApply，limit 需在运行时设置
            ctx.history.limit(100);
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
        <NodeDebugPanel debugMap={nodeDebugMap} />
      </div>

      <NodeConfigDrawer
        open={configDrawerOpen}
        nodeId={selectedNodeId}
        meta={selectedNodeMeta}
        values={configValues}
        onChange={handleConfigChange}
        pickerNodes={pickerNodes}
        keyToMeta={keyToMeta}
        outputs={nodeOutputs}
        onOutputsChange={handleOutputsChange}
        datasetOptions={datasetOptions}
        upstreamInputs={upstreamInputs}
        onAddNext={(typeKey) => {
          // V10：配置抽屉里点"下一步"，以当前选中节点为 source 自动连线
          const fromNodeId = selectedNodeId ?? undefined;
          setSelectedNodeId(null);
          setConfigDrawerOpen(false);
          addNode(typeKey, { fromNodeId });
        }}
        onClose={() => setConfigDrawerOpen(false)}
        onRequestDelete={() => {
          setDeleteTargetIds(selectedNodeId ? [selectedNodeId] : []);
          setDeleteNodeOpen(true);
        }}
        debugRunning={nodeDebugRunning}
        debugResult={nodeDebugResult}
        onDebug={() => void handleDebugNode()}
      />

      <RenameNodeModal
        target={renameTarget}
        onChange={(value) => setRenameTarget((prev) => (prev ? { ...prev, value } : prev))}
        onConfirm={confirmCardRename}
        onCancel={() => setRenameTarget(null)}
      />

      <DeleteNodeModal
        open={deleteNodeOpen}
        targetIds={deleteTargetIds}
        selectedNodeId={selectedNodeId}
        selectedNodeTitle={selectedNodeMeta?.title}
        onConfirm={confirmDeleteNode}
        onCancel={() => { setDeleteNodeOpen(false); setDeleteTargetIds([]); }}
      />

      <RunInputsModal
        open={runModalOpen}
        params={startParams}
        values={runInputs}
        onChange={(patch) => setRunInputs((prev) => ({ ...prev, ...patch }))}
        onCancel={() => setRunModalOpen(false)}
        onOk={() => {
          setRunModalOpen(false);
          doRun(runInputs);
        }}
      />

      {/* 变量引用抽屉（U-L2） */}
      <VariablesDrawer
        open={variablesDrawerOpen}
        onClose={() => setVariablesDrawerOpen(false)}
        nodes={pickerNodes}
        keyToMeta={keyToMeta}
      />

      {/* 会话管理抽屉（N9-05） */}
      <ConversationDrawer
        open={conversationDrawerOpen}
        applicationId={id}
        onClose={() => setConversationDrawerOpen(false)}
      />

      <VersionHistoryDrawer
        open={versionDrawerOpen}
        versions={versions}
        onClose={() => setVersionDrawerOpen(false)}
        onRollback={handleRollback}
      />

      <ApprovalDrawer
        open={approvalState.open}
        payload={approvalState.payload}
        approver={approvalApprover}
        comment={approvalComment}
        onApproverChange={setApprovalApprover}
        onCommentChange={setApprovalComment}
        onClose={() => setApprovalState((prev) => ({ ...prev, open: false }))}
        onSubmit={(approved) => handleApprovalSubmit(approved)}
      />
    </div>
  );
}
