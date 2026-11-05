/** 用户端 workflow API：与后端 web/user/routers/workflow.py 契约对齐。 */

import { postSseStream } from './agentRun'
import { request } from './client'
import type { WorkflowStreamEvent } from '../features/workflow/state/workflowReducer'
import type { RunHistoryItem, WorkflowSchema } from '../features/workflow/types'

interface StreamOptions {
  signal?: AbortSignal
}

export function fetchWorkflowSchema(agentId: string): Promise<WorkflowSchema> {
  return request<WorkflowSchema>(`/user/agents/${agentId}/workflow/schema`)
}

export function runWorkflowStream(
  agentId: string,
  body: { inputs: Record<string, unknown>; thread_id?: string },
  onEvent: (evt: WorkflowStreamEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  return postSseStream<WorkflowStreamEvent>(
    `/user/agents/${agentId}/workflow/run/stream`,
    { inputs: body.inputs, thread_id: body.thread_id || undefined },
    onEvent,
    options,
  )
}

export function resumeWorkflowStream(
  agentId: string,
  threadId: string,
  body: { approved: boolean; comment?: string },
  onEvent: (evt: WorkflowStreamEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  return postSseStream<WorkflowStreamEvent>(
    `/user/agents/${agentId}/workflow/runs/${encodeURIComponent(threadId)}/resume/stream`,
    { approved: body.approved, comment: body.comment ?? '' },
    onEvent,
    options,
  )
}

export function listWorkflowRuns(agentId: string, limit = 50): Promise<RunHistoryItem[]> {
  return request<RunHistoryItem[]>(`/user/agents/${agentId}/runs?limit=${limit}`)
}

export function listWorkflowApprovals(agentId: string, limit = 50): Promise<RunHistoryItem[]> {
  return request<RunHistoryItem[]>(`/user/agents/${agentId}/approvals?limit=${limit}`)
}

export interface NodeExecutionDetail {
  id: string
  node_id: string
  node_type: string | null
  input: unknown
  output: unknown
  error_message: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  usage: Record<string, unknown> | null
}

export interface RunDetail {
  run: RunHistoryItem
  node_executions: NodeExecutionDetail[]
}

export function fetchRunDetail(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/user/runs/${runId}`)
}
