/** workflow SSE 事件 → 运行状态归约器（纯函数，供 P3 useWorkflowRun 与单测复用）。 */

import {
  EMPTY_RUN_STATE,
  type ApprovalPayload,
  type WorkflowNodeState,
  type WorkflowRunState,
} from '../types'

export type WorkflowStreamEvent =
  | { event: 'run_start'; data: { run_id?: string; thread_id?: string; resuming?: boolean } }
  | { event: 'node_start'; data: { node_id: string; node_type?: string; title?: string; inputs?: unknown } }
  | {
      event: 'node_end'
      data: {
        node_id: string
        status?: string
        outputs?: unknown
        duration_ms?: number
        error?: string
      }
    }
  | { event: 'llm_token'; data: { node_id?: string; delta?: string } }
  | { event: 'result'; data: { output: unknown; run_id?: string; thread_id?: string } }
  | {
      event: 'interrupted'
      data: { approval: ApprovalPayload; run_id?: string; thread_id?: string }
    }
  | { event: 'error'; data: { message: string; code?: string } }
  | { event: 'final'; data: Record<string, never> }

function withNode(
  state: WorkflowRunState,
  nodeId: string,
  patch: Partial<WorkflowNodeState>,
): WorkflowRunState {
  const prev = state.nodes[nodeId]
  const node: WorkflowNodeState = {
    nodeId,
    nodeType: undefined,
    title: undefined,
    status: 'running',
    streamingText: '',
    ...prev,
    ...patch,
  }
  const nodeOrder = state.nodeOrder.includes(nodeId)
    ? state.nodeOrder
    : [...state.nodeOrder, nodeId]
  return { ...state, nodeOrder, nodes: { ...state.nodes, [nodeId]: node } }
}

export function workflowReducer(
  state: WorkflowRunState,
  evt: WorkflowStreamEvent,
): WorkflowRunState {
  switch (evt.event) {
    case 'run_start': {
      // 审批续跑（resuming）保留已有轨迹，新运行则整屏重置
      const base = evt.data.resuming ? state : EMPTY_RUN_STATE
      return {
        ...base,
        phase: 'running',
        runId: evt.data.run_id ?? state.runId,
        threadId: evt.data.thread_id ?? state.threadId,
      }
    }
    case 'node_start':
      return withNode(state, evt.data.node_id, {
        nodeType: evt.data.node_type,
        title: evt.data.title,
        status: 'running',
        inputs: evt.data.inputs,
        error: undefined,
      })
    case 'node_end': {
      const status = evt.data.status === 'error' ? 'error' : 'success'
      return withNode(state, evt.data.node_id, {
        status,
        outputs: evt.data.outputs,
        durationMs: evt.data.duration_ms,
        error: evt.data.error,
      })
    }
    case 'llm_token': {
      const nodeId = evt.data.node_id ?? ''
      const delta = evt.data.delta ?? ''
      if (!nodeId || !delta) return state
      const prev = state.nodes[nodeId]
      if (!prev) return state
      return withNode(state, nodeId, { streamingText: prev.streamingText + delta })
    }
    case 'result':
      // 后端失败时也会补发 result(output=null)，错误态优先于结果展示
      if (state.phase === 'error') return state
      return {
        ...state,
        phase: 'success',
        result: {
          output: evt.data.output,
          runId: evt.data.run_id ?? state.runId ?? '',
          threadId: evt.data.thread_id ?? state.threadId ?? '',
        },
      }
    case 'interrupted':
      return {
        ...state,
        phase: 'interrupted',
        approval: evt.data.approval,
        runId: evt.data.run_id ?? state.runId,
        threadId: evt.data.thread_id ?? state.threadId,
      }
    case 'error':
      return { ...state, phase: 'error', error: { message: evt.data.message, code: evt.data.code } }
    case 'final':
      return state
  }
}
