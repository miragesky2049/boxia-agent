import { describe, expect, it } from 'vitest'
import { EMPTY_RUN_STATE } from '../types'
import { workflowReducer } from './workflowReducer'

describe('workflowReducer', () => {
  it('run_start 默认整屏重置轨迹', () => {
    const withNodes = workflowReducer(EMPTY_RUN_STATE, {
      event: 'node_start',
      data: { node_id: 'n1' },
    })
    const next = workflowReducer(withNodes, {
      event: 'run_start',
      data: { run_id: 'r2', thread_id: 't2' },
    })
    expect(next.nodeOrder).toEqual([])
    expect(next.phase).toBe('running')
    expect(next.runId).toBe('r2')
  })

  it('run_start resuming=true 保留已有轨迹（审批续跑衔接）', () => {
    const withNodes = workflowReducer(EMPTY_RUN_STATE, {
      event: 'node_start',
      data: { node_id: 'n1' },
    })
    const next = workflowReducer(withNodes, {
      event: 'run_start',
      data: { run_id: 'r2', thread_id: 't2', resuming: true },
    })
    expect(next.nodeOrder).toEqual(['n1'])
    expect(next.phase).toBe('running')
  })

  it('node_start/node_end 归并同一节点并记录时长与输出', () => {
    let state = workflowReducer(EMPTY_RUN_STATE, {
      event: 'node_start',
      data: { node_id: 'n1', node_type: 'llm', title: '分析' },
    })
    state = workflowReducer(state, {
      event: 'node_end',
      data: { node_id: 'n1', status: 'success', outputs: { ok: 1 }, duration_ms: 42 },
    })
    expect(state.nodeOrder).toEqual(['n1'])
    expect(state.nodes.n1.status).toBe('success')
    expect(state.nodes.n1.durationMs).toBe(42)
    expect(state.nodes.n1.title).toBe('分析')
  })

  it('interrupted 切到等待审批并保存 approval 与 thread', () => {
    const state = workflowReducer(EMPTY_RUN_STATE, {
      event: 'interrupted',
      data: { approval: { instructions: '请审批' }, run_id: 'r1', thread_id: 't1' },
    })
    expect(state.phase).toBe('interrupted')
    expect(state.approval).toEqual({ instructions: '请审批' })
    expect(state.threadId).toBe('t1')
  })

  it('result 后 error 不再覆盖成功态；error 后 result 保持错误态', () => {
    const success = workflowReducer(EMPTY_RUN_STATE, {
      event: 'result',
      data: { output: 'ok' },
    })
    expect(success.phase).toBe('success')

    let state = workflowReducer(EMPTY_RUN_STATE, {
      event: 'error',
      data: { message: 'boom', code: 'workflow_failed' },
    })
    state = workflowReducer(state, { event: 'result', data: { output: null } })
    expect(state.phase).toBe('error')
    expect(state.error?.message).toBe('boom')
    expect(state.result).toBeNull()
  })

  it('llm_token 仅在节点已登记时追加流式文本', () => {
    let state = workflowReducer(EMPTY_RUN_STATE, {
      event: 'node_start',
      data: { node_id: 'n1', node_type: 'llm' },
    })
    state = workflowReducer(state, { event: 'llm_token', data: { node_id: 'n1', delta: '第一段' } })
    state = workflowReducer(state, { event: 'llm_token', data: { node_id: 'n1', delta: '第二段' } })
    state = workflowReducer(state, { event: 'llm_token', data: { node_id: 'missing', delta: 'x' } })
    expect(state.nodes.n1.streamingText).toBe('第一段第二段')
    expect(state.nodeOrder).toEqual(['n1'])
  })
})
