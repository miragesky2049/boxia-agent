/** workflow 工作台领域类型：与后端 web/user/routers/workflow.py 的事件/响应契约对齐。 */

export type WorkflowParamType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'object'
  | 'file'
  | 'image'
  | 'array[string]'
  | 'array[number]'
  | 'array[object]'

export interface WorkflowParam {
  name: string
  type: WorkflowParamType
  required: boolean
  description: string
  default_value: unknown
}

export interface WorkflowSchema {
  application_id: string
  name: string
  description: string
  flow_type: string
  inputs: WorkflowParam[]
  has_human_approval: boolean
}

export interface ApprovalPayload {
  type?: string
  node_id?: string
  node_title?: string
  assignee_role?: string
  instructions?: string
  snapshot?: unknown
}

export type NodeStatus = 'running' | 'success' | 'error'

export interface WorkflowNodeState {
  nodeId: string
  nodeType?: string
  title?: string
  status: NodeStatus
  inputs?: unknown
  outputs?: unknown
  durationMs?: number
  error?: string
  /** LLM 节点流式 token 累积文本 */
  streamingText: string
}

export type WorkflowPhase = 'idle' | 'running' | 'success' | 'error' | 'interrupted'

export interface WorkflowRunState {
  phase: WorkflowPhase
  runId: string | null
  threadId: string | null
  nodeOrder: string[]
  nodes: Record<string, WorkflowNodeState>
  result: { output: unknown; runId: string; threadId: string } | null
  approval: ApprovalPayload | null
  error: { message: string; code?: string } | null
}

export const EMPTY_RUN_STATE: WorkflowRunState = {
  phase: 'idle',
  runId: null,
  threadId: null,
  nodeOrder: [],
  nodes: {},
  result: null,
  approval: null,
  error: null,
}

/** 审批上下文：roleCode 为 null 表示无法判定（降级为纯等待）。 */
export interface ApprovalContext {
  canApprove: boolean
  roleCode: string | null
}

export interface RunHistoryItem {
  id: string
  thread_id: string | null
  execute_status: 'running' | 'success' | 'error' | 'interrupted'
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  interrupt_payload?: ApprovalPayload | null
}

/** 工作台共享：当前审批角色可审性判定。 */
export function canApproveRun(
  approval: ApprovalPayload | null,
  roleCode: string | null,
): boolean {
  if (!approval) return false
  const requiredRole = approval.assignee_role ?? ''
  if (!requiredRole || !roleCode) return false
  return roleCode === 'superadmin' || roleCode === requiredRole
}
