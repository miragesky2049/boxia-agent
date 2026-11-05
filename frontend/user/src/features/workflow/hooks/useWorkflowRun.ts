import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchRunDetail,
  resumeWorkflowStream,
  runWorkflowStream,
} from '../../../api/workflow'
import type { RunDetail } from '../../../api/workflow'
import { EMPTY_RUN_STATE, type RunHistoryItem, type WorkflowRunState } from '../types'
import { workflowReducer, type WorkflowStreamEvent } from '../state/workflowReducer'

function errorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message : '运行失败，请稍后重试'
}

function toEvents(detail: RunDetail): WorkflowStreamEvent[] {
  const events: WorkflowStreamEvent[] = [
    {
      event: 'run_start',
      data: { run_id: detail.run.id, thread_id: detail.run.thread_id ?? undefined },
    },
  ]
  for (const ne of detail.node_executions) {
    events.push({
      event: 'node_start',
      data: { node_id: ne.node_id, node_type: ne.node_type ?? undefined, inputs: ne.input ?? undefined },
    })
    const finished = ne.finished_at !== null
    if (finished) {
      events.push({
        event: 'node_end',
        data: {
          node_id: ne.node_id,
          status: ne.error_message ? 'error' : 'success',
          outputs: ne.output ?? undefined,
          duration_ms: ne.duration_ms ?? undefined,
          error: ne.error_message ?? undefined,
        },
      })
    }
  }
  if (detail.run.execute_status === 'success') {
    events.push({
      event: 'result',
      data: { output: detail.run.output, run_id: detail.run.id, thread_id: detail.run.thread_id ?? undefined },
    })
  } else if (detail.run.execute_status === 'error') {
    events.push({ event: 'error', data: { message: detail.run.error_message ?? '运行失败' } })
  } else if (detail.run.execute_status === 'interrupted') {
    events.push({
      event: 'interrupted',
      data: {
        approval: detail.run.interrupt_payload ?? {},
        run_id: detail.run.id,
        thread_id: detail.run.thread_id ?? undefined,
      },
    })
  }
  return events
}

interface UseWorkflowRunResult {
  state: WorkflowRunState
  submittingApproval: boolean
  run: (inputs: Record<string, unknown>) => void
  stop: () => void
  retry: () => void
  approve: (comment: string) => void
  reject: (comment: string) => void
  loadRun: (item: RunHistoryItem) => Promise<void>
}

/** workflow 运行状态机：SSE 事件 → reducer；llm_token 按帧合批；支持停止/重试/审批续跑/历史回放。 */
export function useWorkflowRun(
  agentId: string | undefined,
  onFinished?: () => void,
): UseWorkflowRunResult {
  const [state, setState] = useState<WorkflowRunState>(EMPTY_RUN_STATE)
  const [submittingApproval, setSubmittingApproval] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const pendingTokensRef = useRef<Record<string, string>>({})
  const rafRef = useRef<number | null>(null)
  const lastInputsRef = useRef<Record<string, unknown>>({})
  const finishedRef = useRef(onFinished)
  finishedRef.current = onFinished

  const flushTokens = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    const pending = pendingTokensRef.current
    pendingTokensRef.current = {}
    for (const [nodeId, delta] of Object.entries(pending)) {
      setState((prev) => workflowReducer(prev, { event: 'llm_token', data: { node_id: nodeId, delta } }))
    }
  }, [])

  const dispatch = useCallback(
    (evt: WorkflowStreamEvent) => {
      if (evt.event === 'llm_token') {
        const nodeId = evt.data.node_id ?? ''
        if (!nodeId || !evt.data.delta) return
        pendingTokensRef.current[nodeId] = (pendingTokensRef.current[nodeId] ?? '') + evt.data.delta
        if (rafRef.current === null) {
          rafRef.current = requestAnimationFrame(() => {
            rafRef.current = null
            flushTokens()
          })
        }
        return
      }
      flushTokens()
      setState((prev) => workflowReducer(prev, evt))
    },
    [flushTokens],
  )

  useEffect(() => () => {
    abortRef.current?.abort()
    if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
  }, [])

  const stream = useCallback(
    async (fn: (onEvent: (evt: WorkflowStreamEvent) => void, signal: AbortSignal) => Promise<void>) => {
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      try {
        await fn((evt) => {
          dispatch(evt)
          if (evt.event === 'result' || evt.event === 'error' || evt.event === 'interrupted' || evt.event === 'final') {
            finishedRef.current?.()
          }
        }, controller.signal)
      } catch (err) {
        if (controller.signal.aborted) return
        setState((prev) =>
          workflowReducer(prev, { event: 'error', data: { message: errorText(err), code: 'stream_failed' } }),
        )
        finishedRef.current?.()
      }
    },
    [dispatch],
  )

  const run = useCallback(
    (inputs: Record<string, unknown>) => {
      if (!agentId) return
      lastInputsRef.current = inputs
      void stream((onEvent, signal) => runWorkflowStream(agentId, { inputs }, onEvent, { signal }))
    },
    [agentId, stream],
  )

  const retry = useCallback(() => run(lastInputsRef.current), [run])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    flushTokens()
    setState((prev) =>
      prev.phase === 'running'
        ? { ...prev, phase: 'error', error: { message: '已手动停止运行。', code: 'cancelled' } }
        : prev,
    )
  }, [flushTokens])

  const resume = useCallback(
    (approved: boolean, comment: string) => {
      const threadId = state.threadId
      if (!agentId || !threadId) {
        setState((prev) => ({
          ...prev,
          phase: 'error',
          error: { message: '缺少运行线程信息，无法提交审批。', code: 'missing_thread' },
        }))
        return
      }
      setSubmittingApproval(true)
      void (async () => {
        try {
          await stream((onEvent, signal) =>
            resumeWorkflowStream(agentId, threadId, { approved, comment }, onEvent, { signal }),
          )
        } finally {
          setSubmittingApproval(false)
        }
      })()
    },
    [agentId, state.threadId, stream],
  )

  const approve = useCallback((comment: string) => resume(true, comment), [resume])
  const reject = useCallback((comment: string) => resume(false, comment), [resume])

  const loadRun = useCallback(
    async (item: RunHistoryItem) => {
      abortRef.current?.abort()
      flushTokens()
      const detail = await fetchRunDetail(item.id)
      let next = EMPTY_RUN_STATE
      for (const evt of toEvents(detail)) next = workflowReducer(next, evt)
      setState(next)
    },
    [flushTokens],
  )

  return { state, submittingApproval, run, stop, retry, approve, reject, loadRun }
}
