import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentStreamEvent, ChatflowStreamEvent } from '../../../api/agentRun'
import { runAgentStream, runChatflowStream } from '../../../api/agentRun'
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
const agentRun = vi.mocked(runAgentStream)

function emitAgent(events: AgentStreamEvent[]) {
  return async (
    _agentId: string,
    _body: unknown,
    onEvent: (event: AgentStreamEvent) => void,
  ) => {
    events.forEach(onEvent)
  }
}

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

// 0074 PRD F8/F9/F10（M3）：统一入口、服务端记忆、审批挂起/续跑
describe('useChatSession 智能体审批协议', () => {
  beforeEach(() => {
    agentRun.mockReset()
  })

  it('agent 型 send 省略 history（启用服务端记忆）且透传 images', async () => {
    agentRun.mockImplementation(emitAgent([
      { event: 'run_start', data: { run_id: 'r1', tools: [] } },
      { event: 'result', data: { content: '图里有只猫', conversation_id: 'c1' } as never },
    ]))

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'agent' }),
    )

    await act(async () => {
      await result.current.send('看图', ['http://img/a.png'])
    })

    const body = agentRun.mock.calls[0][1] as Record<string, unknown>
    expect(body).toMatchObject({
      message: '看图',
      images: ['http://img/a.png'],
    })
    expect(body.history).toBeUndefined()
  })

  it('interrupted 帧产出审批卡并登记 pendingApproval', async () => {
    agentRun.mockImplementation(emitAgent([
      { event: 'run_start', data: { run_id: 'r1', tools: ['send_email'] } },
      { event: 'interrupted', data: {
        approval: { type: 'tool_approval', awaiting_calls: [
          { id: 'c1', name: 'send_email', arguments: '{"to":"boss"}' },
        ] },
        conversation_id: 'c1', thread_id: 'c1:sub1', run_id: 'r1',
      } },
    ]))

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'agent' }),
    )

    await act(async () => {
      await result.current.send('发邮件给老板')
    })

    expect(result.current.pendingApproval).toMatchObject({
      threadId: 'c1:sub1',
      runId: 'r1',
      calls: [{ id: 'c1', name: 'send_email' }],
    })
    const card = result.current.messages.find((item) => item.approval)
    expect(card?.approval?.calls[0].name).toBe('send_email')
    expect(result.current.streaming).toBe(false)
  })

  it('批准裁决：裁决文案上屏并以 resume+thread_id 续跑', async () => {
    agentRun.mockImplementation(async (_agentId, body, onEvent) => {
      if (body.resume) {
        onEvent({ event: 'run_start', data: { run_id: 'r1', tools: [] } })
        onEvent({ event: 'result', data: { content: '已发送并汇报。', conversation_id: 'c1' } as never })
        return
      }
      onEvent({ event: 'run_start', data: { run_id: 'r1', tools: [] } })
      onEvent({ event: 'interrupted', data: {
        approval: { type: 'tool_approval', awaiting_calls: [{ id: 'c1', name: 'send_email', arguments: '{}' }] },
        conversation_id: 'c1', thread_id: 'c1:sub1', run_id: 'r1',
      } })
    })

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'agent' }),
    )

    // 无挂起时直接裁决应被忽略（不发起请求）
    await act(async () => {
      await result.current.resolveApproval(true, '越权代答')
    })
    expect(agentRun.mock.calls).toHaveLength(0)

    await act(async () => {
      await result.current.send('发邮件给老板')
    })
    await act(async () => {
      await result.current.resolveApproval(true, '可以发')
    })

    const resumeCall = agentRun.mock.calls[1][1] as Record<string, unknown>
    expect(resumeCall).toMatchObject({
      message: '',
      conversation_id: 'c1',
      thread_id: 'c1:sub1',
      resume: { approved: true, comment: '可以发' },
    })
    // 与后端 _approval_decision_text 同构的裁决文案气泡
    expect(result.current.messages.map((item) => item.content)).toContain(
      '批准执行工具调用（理由：可以发）',
    )
    expect(result.current.pendingApproval).toBeNull()
    const last = result.current.messages[result.current.messages.length - 1]
    expect(last.content).toBe('已发送并汇报。')
  })

  it('拒绝裁决走同一续跑通道（approved=false）', async () => {
    agentRun.mockImplementation(emitAgent([
      { event: 'run_start', data: { run_id: 'r2', tools: [] } },
      { event: 'interrupted', data: {
        approval: { type: 'tool_approval', awaiting_calls: [] },
        conversation_id: 'c1', thread_id: 'c1', run_id: 'r2',
      } },
    ]))

    const { result } = renderHook(() =>
      useChatSession({ agentId: 'agent-1', flowType: 'agent' }),
    )

    await act(async () => {
      await result.current.send('触发挂起')
    })
    await act(async () => {
      await result.current.resolveApproval(false, '先别发')
    })

    const rejectCall = agentRun.mock.calls[1][1] as Record<string, unknown>
    expect(rejectCall.resume).toEqual({ approved: false, comment: '先别发' })
  })
})
