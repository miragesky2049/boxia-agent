import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getAgent } from '../api/agents'
import { fetchWorkflowSchema } from '../api/workflow'
import { useAuth } from '../auth/AuthContext'
import WorkflowWorkbench from '../features/workflow/WorkflowWorkbench'
import { workflowReducer, type WorkflowStreamEvent } from '../features/workflow/state/workflowReducer'
import {
  buildMockRunState,
  isMockScenario,
  mockApprovals,
  mockResumeEvents,
  mockRuns,
  mockSchema,
  mockTokenDeltas,
  type MockScenario,
} from '../features/workflow/mock/mockWorkflow'
import { useWorkflowHistory } from '../features/workflow/hooks/useWorkflowHistory'
import { useWorkflowRun } from '../features/workflow/hooks/useWorkflowRun'
import {
  EMPTY_RUN_STATE,
  canApproveRun,
  type RunHistoryItem,
  type WorkflowRunState,
  type WorkflowSchema,
} from '../features/workflow/types'
import '../features/workflow/workflow.css'

export default function WorkflowPage() {
  const [searchParams] = useSearchParams()
  const mockParam = searchParams.get('wfMock')
  const scenario: MockScenario | null = isMockScenario(mockParam) ? mockParam : null
  if (scenario !== null) return <WorkflowMockView scenario={scenario} />
  return <WorkflowRealView />
}

function WorkflowRealView() {
  const { agentId } = useParams<{ agentId: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const [schema, setSchema] = useState<WorkflowSchema | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [chatflowRedirect, setChatflowRedirect] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)

  const history = useWorkflowHistory(agentId)
  const reloadRef = useRef(history.reload)
  reloadRef.current = history.reload
  const onFinished = useCallback(() => void reloadRef.current(), [])
  const run = useWorkflowRun(agentId, onFinished)

  useEffect(() => {
    if (!agentId) return
    let active = true
    fetchWorkflowSchema(agentId)
      .then((data) => {
        if (active) setSchema(data)
      })
      .catch(async (err: unknown) => {
        if (!active) return
        const detail = err instanceof Error ? err.message : '加载工作流入参失败'
        setLoadError(detail)
        const agent = await getAgent(agentId).catch(() => null)
        if (active && agent?.flow_type === 'chatflow') setChatflowRedirect(`/agents/${agentId}/chat`)
      })
    return () => {
      active = false
    }
  }, [agentId])

  const approvalContext = useMemo(
    () => ({ canApprove: canApproveRun(run.state.approval, user?.role_code ?? null), roleCode: user?.role_code ?? null }),
    [run.state.approval, user?.role_code],
  )

  const refreshApproval = useCallback(async () => {
    await history.reload()
    const threadId = run.state.threadId
    if (!threadId) return
    const settled = history.runs.find((r) => r.thread_id === threadId && r.execute_status !== 'interrupted')
    if (settled) await run.loadRun(settled)
  }, [history, run])

  const openHistoryRun = useCallback(
    (item: RunHistoryItem) => {
      setHistoryOpen(false)
      void run.loadRun(item).catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : '加载运行详情失败')
      })
    },
    [run],
  )

  if (chatflowRedirect) return <Navigate to={chatflowRedirect} replace />

  return (
    <WorkflowWorkbench
      agentName={schema?.name || '工作流应用'}
      schema={schema}
      state={run.state}
      approvalContext={approvalContext}
      submittingApproval={run.submittingApproval}
      runs={history.runs}
      approvals={history.approvals}
      historyOpen={historyOpen}
      onHistoryOpenChange={setHistoryOpen}
      onBack={() => navigate('/')}
      onRun={run.run}
      onStop={run.stop}
      onApprove={run.approve}
      onReject={run.reject}
      onRefreshApproval={() => void refreshApproval()}
      onRetry={run.retry}
      onSelectHistoryRun={openHistoryRun}
      onLoadError={loadError}
    />
  )
}

function WorkflowMockView({ scenario }: { scenario: MockScenario }) {
  const navigate = useNavigate()
  const [state, setState] = useState<WorkflowRunState>(buildMockRunState(scenario))
  const [historyOpen, setHistoryOpen] = useState(false)
  const [submittingApproval, setSubmittingApproval] = useState(false)
  const timers = useRef<number[]>([])

  const dispatch = (evt: WorkflowStreamEvent) => setState((prev) => workflowReducer(prev, evt))

  const clearTimers = () => {
    for (const id of timers.current) window.clearTimeout(id)
    timers.current = []
  }

  useEffect(() => clearTimers, [])

  useEffect(() => {
    if (scenario !== 'running') return
    let index = 0
    const id = window.setInterval(() => {
      dispatch({
        event: 'llm_token',
        data: { node_id: 'analyze', delta: mockTokenDeltas[index % mockTokenDeltas.length] },
      })
      index += 1
      if (index >= mockTokenDeltas.length * 3) window.clearInterval(id)
    }, 900)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scenario 变化才重建
  }, [scenario])

  const runEventStream = (events: WorkflowStreamEvent[], stepMs = 320) => {
    clearTimers()
    setState(EMPTY_RUN_STATE)
    events.forEach((evt, i) => {
      const id = window.setTimeout(() => dispatch(evt), stepMs * (i + 1))
      timers.current.push(id)
    })
  }

  const roleCode = scenario === 'approval' ? 'leader' : scenario === 'waiting' ? 'viewer' : null
  const approvalContext = useMemo(
    () => ({ canApprove: canApproveRun(state.approval, roleCode), roleCode }),
    [state.approval, roleCode],
  )

  const handleRun = (inputs: Record<string, unknown>) => {
    const events: WorkflowStreamEvent[] = [
      { event: 'run_start', data: { run_id: `mock-run-${Date.now()}`, thread_id: 'mock-thread' } },
      { event: 'node_start', data: { node_id: 'start', node_type: 'start', title: '开始', inputs } },
      { event: 'node_end', data: { node_id: 'start', status: 'success', outputs: inputs, duration_ms: 10 } },
      { event: 'node_start', data: { node_id: 'search', node_type: 'knowledge', title: '知识库检索' } },
      { event: 'node_end', data: { node_id: 'search', status: 'success', outputs: { hits: 5 }, duration_ms: 400 } },
      { event: 'node_start', data: { node_id: 'analyze', node_type: 'llm', title: '分析与撰写' } },
      { event: 'llm_token', data: { node_id: 'analyze', delta: '正在生成分析草稿…' } },
      { event: 'node_end', data: { node_id: 'analyze', status: 'success', outputs: { draft: 'ok' }, duration_ms: 5000 } },
      {
        event: 'interrupted',
        data: { approval: mockApprovals[0].interrupt_payload ?? {}, run_id: 'mock-run-int', thread_id: 'mock-thread' },
      },
    ]
    runEventStream(events)
  }

  const handleApprove = () => {
    setSubmittingApproval(true)
    runEventStream(mockResumeEvents)
    const id = window.setTimeout(() => setSubmittingApproval(false), mockResumeEvents.length * 320 + 100)
    timers.current.push(id)
  }

  const handleReject = () => {
    setState((prev) => ({
      ...prev,
      phase: 'error',
      approval: null,
      error: { message: '审批已驳回，运行终止并保留草稿。', code: 'approval_rejected' },
    }))
  }

  return (
    <WorkflowWorkbench
      agentName={mockSchema.name}
      schema={mockSchema}
      state={state}
      approvalContext={approvalContext}
      submittingApproval={submittingApproval}
      runs={mockRuns}
      approvals={mockApprovals}
      historyOpen={historyOpen}
      onHistoryOpenChange={setHistoryOpen}
      onBack={() => navigate('/')}
      onRun={handleRun}
      onStop={() =>
        setState((prev) => ({ ...prev, phase: 'error', error: { message: '已手动停止运行。', code: 'cancelled' } }))
      }
      onApprove={handleApprove}
      onReject={handleReject}
      onRefreshApproval={() => undefined}
      onRetry={() => handleRun({ query: '2026 智能座舱市场' })}
    />
  )
}
