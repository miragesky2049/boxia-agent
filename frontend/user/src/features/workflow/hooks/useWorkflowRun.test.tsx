import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchRunDetail,
  resumeWorkflowStream,
  runWorkflowStream,
} from '../../../api/workflow'
import type { RunDetail } from '../../../api/workflow'
import { useWorkflowRun } from './useWorkflowRun'

vi.mock('../../../api/workflow', () => ({
  runWorkflowStream: vi.fn(),
  resumeWorkflowStream: vi.fn(),
  fetchRunDetail: vi.fn(),
}))

const runMock = vi.mocked(runWorkflowStream)
const resumeMock = vi.mocked(resumeWorkflowStream)
const detailMock = vi.mocked(fetchRunDetail)

beforeEach(() => {
  runMock.mockReset()
  resumeMock.mockReset()
  detailMock.mockReset()
  // 同步执行 rAF 回调，让 token 合批在测试内确定性地 flush
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    cb(0)
    return 1
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
})

describe('useWorkflowRun 运行态', () => {
  it('run 流事件驱动状态机并在结束时回调 onFinished', async () => {
    runMock.mockImplementation(async (_agentId, _body, onEvent) => {
      onEvent({ event: 'run_start', data: { run_id: 'r1', thread_id: 't1' } })
      onEvent({ event: 'node_start', data: { node_id: 'n1', node_type: 'llm', title: '分析' } })
      onEvent({ event: 'llm_token', data: { node_id: 'n1', delta: '你好' } })
      onEvent({ event: 'llm_token', data: { node_id: 'n1', delta: '世界' } })
      onEvent({ event: 'node_end', data: { node_id: 'n1', status: 'success', duration_ms: 5 } })
      onEvent({ event: 'result', data: { output: 'ok', run_id: 'r1', thread_id: 't1' } })
      onEvent({ event: 'final', data: {} })
    })
    const onFinished = vi.fn()
    const { result } = renderHook(() => useWorkflowRun('agent-1', onFinished))
    await act(async () => {
      result.current.run({ query: 'x' })
    })
    expect(result.current.state.phase).toBe('success')
    expect(result.current.state.nodes.n1.streamingText).toBe('你好世界')
    expect(onFinished).toHaveBeenCalled()
  })

  it('interrupted 后 approve 走 resume，resuming 续跑保留轨迹', async () => {
    runMock.mockImplementation(async (_agentId, _body, onEvent) => {
      onEvent({ event: 'run_start', data: { run_id: 'r1', thread_id: 't1' } })
      onEvent({ event: 'node_start', data: { node_id: 'n1', node_type: 'start' } })
      onEvent({ event: 'node_end', data: { node_id: 'n1', status: 'success' } })
      onEvent({
        event: 'interrupted',
        data: { approval: { assignee_role: 'leader' }, run_id: 'r1', thread_id: 't1' },
      })
    })
    resumeMock.mockImplementation(async (_agentId, _threadId, _body, onEvent) => {
      onEvent({ event: 'run_start', data: { run_id: 'r2', thread_id: 't1', resuming: true } })
      onEvent({ event: 'node_start', data: { node_id: 'n2', node_type: 'end' } })
      onEvent({ event: 'result', data: { output: 'done', run_id: 'r2', thread_id: 't1' } })
    })
    const { result } = renderHook(() => useWorkflowRun('agent-1'))
    await act(async () => {
      result.current.run({ content: 'c' })
    })
    expect(result.current.state.phase).toBe('interrupted')

    await act(async () => {
      result.current.approve('同意')
    })
    expect(resumeMock).toHaveBeenCalledWith('agent-1', 't1', { approved: true, comment: '同意' }, expect.any(Function), expect.anything())
    expect(result.current.state.phase).toBe('success')
    expect(result.current.state.nodeOrder).toEqual(['n1', 'n2'])
  })

  it('stop 将运行中状态置为已取消错误', async () => {
    let finishStream: (() => void) | undefined
    runMock.mockImplementation(async (_agentId, _body, onEvent) => {
      onEvent({ event: 'run_start', data: { run_id: 'r1', thread_id: 't1' } })
      await new Promise<void>((resolve) => {
        finishStream = resolve
      })
    })
    const { result } = renderHook(() => useWorkflowRun('agent-1'))
    act(() => {
      result.current.run({ query: 'x' })
    })
    await waitFor(() => expect(result.current.state.phase).toBe('running'))
    act(() => {
      result.current.stop()
    })
    expect(result.current.state.phase).toBe('error')
    expect(result.current.state.error?.code).toBe('cancelled')
    finishStream?.()
  })

  it('loadRun 从运行详情回放轨迹与等待审批态', async () => {
    const detail: RunDetail = {
      run: {
        id: 'r1',
        thread_id: 't1',
        execute_status: 'interrupted',
        input: { content: 'c' },
        output: null,
        error_message: null,
        started_at: '2026-11-05T10:00:00Z',
        finished_at: null,
        interrupt_payload: { assignee_role: 'leader', instructions: '请核对' },
      },
      node_executions: [
        {
          id: 'ne1',
          node_id: 'n1',
          node_type: 'start',
          input: { content: 'c' },
          output: { content: 'c' },
          error_message: null,
          started_at: '2026-11-05T10:00:00Z',
          finished_at: '2026-11-05T10:00:01Z',
          duration_ms: 10,
          usage: null,
        },
        {
          id: 'ne2',
          node_id: 'n2',
          node_type: 'human_approval',
          input: null,
          output: null,
          error_message: null,
          started_at: '2026-11-05T10:00:01Z',
          finished_at: null,
          duration_ms: null,
          usage: null,
        },
      ],
    }
    detailMock.mockResolvedValue(detail)
    const { result } = renderHook(() => useWorkflowRun('agent-1'))
    await act(async () => {
      await result.current.loadRun({ ...detail.run })
    })
    expect(result.current.state.phase).toBe('interrupted')
    expect(result.current.state.nodeOrder).toEqual(['n1', 'n2'])
    expect(result.current.state.nodes.n2.status).toBe('running')
    expect(result.current.state.approval).toEqual({ assignee_role: 'leader', instructions: '请核对' })
  })
})
