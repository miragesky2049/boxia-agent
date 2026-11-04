import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatflowStreamEvent } from '../../../api/agentRun'
import { runChatflowStream } from '../../../api/agentRun'
import { useChatSession } from './useChatSession'

vi.mock('../../../api/agentRun', () => ({
  runAgentStream: vi.fn(),
  runChatflowStream: vi.fn(),
}))

vi.mock('../../../api/conversations', () => ({
  listConversations: vi.fn(async () => []),
  listConversationMessages: vi.fn(async () => []),
}))

const chatflowRun = vi.mocked(runChatflowStream)

function emit(events: ChatflowStreamEvent[]) {
  return async (
    _agentId: string,
    _body: unknown,
    onEvent: (event: ChatflowStreamEvent) => void,
  ) => {
    events.forEach(onEvent)
  }
}

describe('useChatSession 对话流协议', () => {
  beforeEach(() => {
    chatflowRun.mockReset()
  })

  it('question 中断登记待回答状态，回答时以 resume 续跑', async () => {
    chatflowRun.mockImplementation(async (_agentId, body, onEvent) => {
      if (body.resume) {
        onEvent({ event: 'output_message', data: { content: '已收到你的选择' } })
        onEvent({ event: 'result', data: { outputs: {} } })
        return
      }
      onEvent({
        event: 'run_start',
        data: { conversation_id: 'c1', thread_id: 't1', run_id: 'r1' },
      })
      onEvent({
        event: 'question',
        data: {
          node_id: 'n1',
          question: '请选择方向',
          options: ['A', 'B'],
          conversation_id: 'c1',
          thread_id: 't1',
          run_id: 'r1',
        },
      })
    })

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'chatflow' }),
    )

    await act(async () => {
      await result.current.send('开始')
    })

    expect(result.current.pendingQuestion).toMatchObject({ options: ['A', 'B'], threadId: 't1' })
    expect(result.current.messages.map((item) => item.content)).toEqual(['开始', '请选择方向'])
    expect(result.current.messages[1].question?.submitted).toBeFalsy()

    await act(async () => {
      await result.current.send('A')
    })

    const secondCall = chatflowRun.mock.calls[1]
    expect(secondCall[1]).toMatchObject({
      message: '',
      conversation_id: 'c1',
      thread_id: 't1',
      resume: { answer: 'A' },
    })
    expect(result.current.pendingQuestion).toBeNull()
    expect(result.current.messages[1].question?.submitted).toBe(true)
    expect(result.current.messages.map((item) => item.content)).toEqual([
      '开始',
      '请选择方向',
      'A',
      '已收到你的选择',
    ])
  })

  it('无 output_message 时用 result.outputs 兜底输出', async () => {
    chatflowRun.mockImplementation(emit([
      { event: 'run_start', data: { conversation_id: 'c2', thread_id: 't2', run_id: 'r2' } },
      { event: 'result', data: { outputs: { output: '兜底输出' } } },
    ]))

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'chatflow' }),
    )

    await act(async () => {
      await result.current.send('你好')
    })

    expect(result.current.messages.map((item) => item.content)).toEqual(['你好', '兜底输出'])
    expect(result.current.streaming).toBe(false)
  })

  it('error 事件产出可重试的错误气泡', async () => {
    chatflowRun.mockImplementation(emit([
      { event: 'error', data: { message: '模型限流' } },
    ]))

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'chatflow' }),
    )

    await act(async () => {
      await result.current.send('你好')
    })

    expect(result.current.messages[1].error?.message).toBe('模型限流')
    expect(result.current.streaming).toBe(false)
  })
})
