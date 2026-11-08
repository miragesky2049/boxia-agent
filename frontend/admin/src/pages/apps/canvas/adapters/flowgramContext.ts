import type { FreeLayoutPluginContext, WorkflowJSON } from '@flowgram.ai/free-layout-editor'

// FlowGram 的公开类型没有覆盖全部运行期 API（playground.config / document.linesManager / history 等），
// 所有 `as any` 都收敛在本文件；页面与组件只通过这里的方法访问画布。
// 升级 FlowGram 时只需核对本文件的取值路径。

export type FlowContext = FreeLayoutPluginContext | null | undefined

export interface ScreenPoint {
  x: number
  y: number
}

export interface ViewportState extends ScreenPoint {
  w: number
  h: number
  zoom: number
}

export interface HistoryState {
  canUndo: boolean
  canRedo: boolean
}

export interface SelectionSnapshot {
  nodeIds: string[]
  nodeTypeKeys: string[]
  lineIds: string[]
}

export interface Disposable {
  dispose?: () => void
}

export const MIN_ZOOM = 0.25
export const MAX_ZOOM = 2

function playgroundConfig(ctx: FlowContext): any {
  return (ctx as any)?.playground?.config
}

function linesManager(ctx: FlowContext): any {
  return (ctx as any)?.document?.linesManager
}

function historyService(ctx: FlowContext): any {
  return (ctx as any)?.history
}

function selectionService(ctx: FlowContext): any {
  return (ctx as any)?.selection
}

function clampZoom(next: number): number {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next))
}

// ========== 缩放 / 平移 / 视图 ==========

export function getZoom(ctx: FlowContext): number {
  return playgroundConfig(ctx)?.zoom ?? 1
}

export function setZoom(ctx: FlowContext, next: number): void {
  playgroundConfig(ctx)?.updateZoom?.(clampZoom(next), true)
}

export function zoomBy(ctx: FlowContext, delta: number): void {
  setZoom(ctx, getZoom(ctx) + delta)
}

export function getScroll(ctx: FlowContext): ScreenPoint {
  const config = playgroundConfig(ctx)
  return {
    x: config?.scrollData?.scrollX ?? config?.scrollX ?? 0,
    y: config?.scrollData?.scrollY ?? config?.scrollY ?? 0,
  }
}

export function setScroll(ctx: FlowContext, x: number, y: number): void {
  playgroundConfig(ctx)?.scroll?.({ scrollX: x, scrollY: y }, false)
}

export function getViewport(ctx: FlowContext): ViewportState | null {
  const config = playgroundConfig(ctx)
  const vp = config?.getViewport?.()
  if (!vp) return null
  return { x: vp.x, y: vp.y, w: vp.width, h: vp.height, zoom: config.zoom ?? 1 }
}

export function fitView(ctx: FlowContext, easing = true): Promise<void> {
  return Promise.resolve(ctx?.document?.fitView?.(easing)).catch(() => undefined)
}

export function scrollToCanvasPoint(ctx: FlowContext, x: number, y: number): void {
  playgroundConfig(ctx)?.scrollToView?.({ position: { x, y }, scrollToCenter: true, easing: true })
}

export function getWorldPosFromMouseEvent(
  ctx: FlowContext,
  event: { clientX: number; clientY: number },
): ScreenPoint | null {
  return playgroundConfig(ctx)?.getPosFromMouseEvent?.(event) ?? null
}

export function worldToScreen(ctx: FlowContext, pos: ScreenPoint): ScreenPoint | null {
  return playgroundConfig(ctx)?.toFixedPos?.(pos) ?? null
}

export function subscribeViewport(ctx: FlowContext, onChange: () => void): Disposable {
  const playground = (ctx as any)?.playground
  const config = playground?.config
  const subscriptions: Disposable[] = []
  if (config?.onConfigChanged) subscriptions.push(config.onConfigChanged(onChange))
  if (playground?.onZoom) subscriptions.push(playground.onZoom(onChange))
  if (playground?.onScroll) subscriptions.push(playground.onScroll(onChange))
  return {
    dispose: () => {
      subscriptions.forEach((d) => d.dispose?.())
    },
  }
}

// ========== 撤销 / 重做 ==========

export function undo(ctx: FlowContext): void {
  historyService(ctx)?.undo?.()
}

export function redo(ctx: FlowContext): void {
  historyService(ctx)?.redo?.()
}

export function getHistoryState(ctx: FlowContext): HistoryState {
  const history = historyService(ctx)
  return {
    canUndo: Boolean(history?.canUndo?.()),
    canRedo: Boolean(history?.canRedo?.()),
  }
}

// onApply 早于撤销栈入栈/出栈，回调后再延后一拍同步可用态
export function subscribeHistory(
  ctx: FlowContext,
  onChange: (state: HistoryState) => void,
): Disposable {
  const history = historyService(ctx)
  if (!history) return {}
  const sync = () => onChange(getHistoryState(ctx))
  sync()
  const disposable = history.onApply?.(() => {
    sync()
    window.setTimeout(sync, 0)
  })
  return disposable || {}
}

// ========== 选中集合 ==========

export function getSelection(ctx: FlowContext): SelectionSnapshot {
  const entities = (selectionService(ctx)?.selection || []) as Array<{
    id?: string
    flowNodeType?: string
  }>
  return buildSelectionSnapshot(entities, getAllLines(ctx))
}

export function subscribeSelection(
  ctx: FlowContext,
  onChange: (snapshot: SelectionSnapshot) => void,
): Disposable {
  const selection = selectionService(ctx)
  if (!selection?.onSelectionChanged) return {}
  return (
    selection.onSelectionChanged((entities: Array<{ id?: string; flowNodeType?: string }>) => {
      onChange(buildSelectionSnapshot(entities || [], getAllLines(ctx)))
    }) || {}
  )
}

export function clearSelection(ctx: FlowContext): void {
  try {
    const selection = selectionService(ctx)
    if (selection) selection.selection = []
  } catch {
    // 选中清理失败不影响调用方结果
  }
}

// 全选节点（N9-09）：SelectionService 只有 selection setter，赋值即触发 onSelectionChanged
export function selectAllNodes(ctx: FlowContext): number {
  const nodes = ((ctx as any)?.document?.nodes || []) as unknown[]
  const selection = selectionService(ctx)
  if (!selection || nodes.length === 0) return 0
  selection.selection = [...nodes]
  return nodes.length
}

function buildSelectionSnapshot(
  entities: Array<{ id?: string; flowNodeType?: string }>,
  lines: Array<{ id: string }>,
): SelectionSnapshot {
  const nodeEntities = entities.filter((entity) => typeof entity?.flowNodeType === 'string')
  const lineIdSet = new Set(lines.map((line) => line.id))
  return {
    nodeIds: nodeEntities.map((entity) => String(entity.id || '')).filter(Boolean),
    nodeTypeKeys: nodeEntities.map((entity) => String(entity.flowNodeType || '')),
    // 选中集合里的非节点实体是连线：linesManager.getLine 只接受端口对象，这里按 id 匹配
    lineIds: entities
      .filter((entity) => !entity?.flowNodeType && entity?.id && lineIdSet.has(String(entity.id)))
      .map((entity) => String(entity.id)),
  }
}

// ========== 节点 ==========

export function toWorkflowJSON(ctx: FlowContext): WorkflowJSON {
  return ctx?.document?.toJSON() as unknown as WorkflowJSON
}

export function getNodeCount(ctx: FlowContext): number {
  return (ctx as any)?.document?.nodes?.length || 0
}

export function getNode(ctx: FlowContext, nodeId: string): any {
  return (ctx as any)?.document?.getNode?.(nodeId)
}

// 实体上的 type 可能是 FlowNodeEntity，节点类型优先取 flowNodeType
export function getNodeTypeKey(
  node: { id?: string; type?: string; flowNodeType?: string | number } | null | undefined,
): string {
  if (!node) return ''
  const flowNodeType = String(node.flowNodeType || '')
  if (flowNodeType) return flowNodeType
  const type = String(node.type || '')
  if (type && type !== 'FlowNodeEntity') return type
  return String(node.id || '').split('-')[0] || ''
}

export function getNodeExtInfo(node: any): Record<string, any> {
  return (node?.getExtInfo?.() || node?.data || {}) as Record<string, any>
}

export function updateNodeExtInfo(node: any, patch: Record<string, any>): void {
  if (!node?.updateExtInfo) return
  node.updateExtInfo({ ...getNodeExtInfo(node), ...patch })
}

export function createNodeByType(
  ctx: FlowContext,
  typeKey: string,
  position: ScreenPoint,
  init: { id: string; data: Record<string, unknown> },
): void {
  const root = getNode(ctx, 'root')
  // 必须走 createWorkflowNodeByType：裸 addNode 不会初始化 TransformData
  ctx?.document?.createWorkflowNodeByType?.(typeKey, position, init, root?.id)
}

export function removeNode(ctx: FlowContext, nodeId: string): boolean {
  try {
    const node = getNode(ctx, nodeId)
    if (node && typeof node.remove === 'function') {
      node.remove()
      return true
    }
    const document = (ctx as any)?.document
    if (typeof document?.removeNode === 'function') {
      document.removeNode(nodeId)
      return true
    }
  } catch {
    // 单个节点删除失败由调用方汇总提示
  }
  return false
}

// ========== 连线 ==========

export function getAllLines(ctx: FlowContext): Array<{ id: string }> {
  return (linesManager(ctx)?.getAllLines?.() || []) as Array<{ id: string }>
}

export function getPortFromMousePos(
  ctx: FlowContext,
  pos: ScreenPoint,
): { id: string; portType?: string } | null {
  return linesManager(ctx)?.getPortFromMousePos?.(pos) ?? null
}

export function getLineFromMousePos(ctx: FlowContext, pos: ScreenPoint): { id: string } | null {
  return linesManager(ctx)?.getCloseInLineFromMousePos?.(pos) ?? null
}

export function getNodeFromMousePos(
  ctx: FlowContext,
  pos: ScreenPoint,
): { flowNodeType?: string } | null {
  return linesManager(ctx)?.getNodeFromMousePos?.(pos) ?? null
}

export function createLine(
  ctx: FlowContext,
  params: { from: string; fromPort: string; to: string; toPort?: string },
): void {
  linesManager(ctx)?.createLine?.(params)
}

export function disposeLinesByIds(ctx: FlowContext, lineIds: string[]): number {
  const wanted = new Set(lineIds)
  let removed = 0
  getAllLines(ctx).forEach((line: { id: string; dispose?: () => void }) => {
    if (wanted.has(line.id)) {
      line.dispose?.()
      removed += 1
    }
  })
  return removed
}
