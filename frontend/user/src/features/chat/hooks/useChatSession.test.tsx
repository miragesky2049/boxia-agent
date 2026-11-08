import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentStreamEvent, ChatflowStreamEvent } from '../../../api/agentRun'
import { runAgentStream, runChatflowStream } from '../../../api/agentRun'
import { listConversationMessages, listConversations } from '../../../api/conversations'
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
const conversationList = vi.mocked(listConversations)
const messageList = vi.mocked(listConversationMessages)

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

// M4 PRD F14.10：接管发言权通告气泡、应答徽标与手动归位（handback）
describe('useChatSession 接管协议', () => {
  beforeEach(() => {
    agentRun.mockReset()
    conversationList.mockReset()
    messageList.mockReset()
    conversationList.mockResolvedValue([])
    messageList.mockResolvedValue([])
  })

  const takeoverFrame: AgentStreamEvent = {
    event: 'handoff',
    data: {
      from_app_id: 'agent-1', to_app_id: 'app-2',
      display_name: '天气专家', returned: false,
    },
  }

  async function startTakeover(result: { current: ReturnType<typeof useChatSession> }) {
    await act(async () => {
      await result.current.send('帮我查天气趋势')
    })
  }

  it('handoff 帧追加通告气泡并登记发言权，下一轮应答气泡带专家徽标', async () => {
    // 真实服务端 result 帧必然后于接管提交：摘要 mock 与提交时间线一致
    conversationList.mockResolvedValue([
      {
        conversation_id: 'c1', title: '查天气', created_at: null, updated_at: null,
        active_application_id: 'app-2', active_application: '天气专家',
      },
    ])
    agentRun.mockImplementation(async (_agentId, body, onEvent) => {
      if (body.message === '帮我查天气趋势') {
        onEvent({ event: 'run_start', data: { run_id: 'r1', tools: [] } })
        onEvent(takeoverFrame)
        onEvent({
          event: 'result',
          data: { content: '', conversation_id: 'c1', finish_reason: 'handed_off' } as never,
        })
        return
      }
      onEvent({ event: 'run_start', data: { run_id: 'r2', tools: [] } })
      onEvent({
        event: 'result',
        data: { content: '明天晴，20 度。', conversation_id: 'c1' } as never,
      })
    })

    const { result } = renderHook(() => useChatSession({ agentId: 'agent-1', flowType: 'agent' }))
    await startTakeover(result)

    expect(result.current.activeHandoff).toEqual({
      applicationId: 'app-2', displayName: '天气专家',
    })
    const notice = result.current.messages.find((item) => item.handoffNotice)
    expect(notice?.handoffNotice).toBe('会话已移交给专家「天气专家」，后续对话由其应答。')
    // 接管轮本身仍由归属应用应答，不打专家徽标
    const takeoverAssistant = result.current.messages.find((item) => item.streaming === false && item.content === '')
    expect(takeoverAssistant?.answeredBy).toBeUndefined()

    await act(async () => {
      await result.current.send('明天穿什么')
    })
    const last = result.current.messages[result.current.messages.length - 1]
    expect(last.content).toBe('明天晴，20 度。')
    expect(last.answeredBy).toBe('天气专家')
  })

  it('handback：handback:true 请求清发言权并追加归位通告；未接管时不发请求', async () => {
    agentRun.mockImplementation(async (_agentId, body, onEvent) => {
      if (body.handback) {
        onEvent({
          event: 'handoff',
          data: {
            from_app_id: 'app-2', to_app_id: 'agent-1',
            display_name: '主助手', returned: true,
          },
        })
        onEvent({ event: 'final', data: {} })
        return
      }
      onEvent(takeoverFrame)
      onEvent({
        event: 'result',
        data: { content: '', conversation_id: 'c1', finish_reason: 'handed_off' } as never,
      })
    })

    const { result } = renderHook(() => useChatSession({ agentId: 'agent-1', flowType: 'agent' }))
    // 未进入接管（无会话/无发言权）时 guard 不发请求
    await act(async () => {
      await result.current.handback()
    })
    expect(agentRun.mock.calls).toHaveLength(0)

    // 接管提交后摘要反映移交（result 帧对齐兜底不误清）
    conversationList.mockResolvedValue([
      {
        conversation_id: 'c1', title: '查天气', created_at: null, updated_at: null,
        active_application_id: 'app-2', active_application: '天气专家',
      },
    ])
    await startTakeover(result)
    // 归位提交后摘要不再显示接管
    conversationList.mockResolvedValue([])
    await act(async () => {
      await result.current.handback()
    })

    const handbackCall = agentRun.mock.calls[1][1] as Record<string, unknown>
    expect(handbackCall).toMatchObject({ conversation_id: 'c1', handback: true })
    expect(result.current.activeHandoff).toBeNull()
    expect(result.current.streaming).toBe(false)
    const notice = result.current.messages[result.current.messages.length - 1]
    expect(notice.handoffNotice).toBe('接管已结束，会话已归位主助手「主助手」。')
  })

  it('历史回放：通告气泡重建、专家轮徽标、接管轮空正文行过滤', async () => {
    conversationList.mockResolvedValue([
      {
        conversation_id: 'c1', title: '查天气', created_at: null, updated_at: null,
        active_application_id: 'app-2', active_application: '天气专家',
      },
    ])
    messageList.mockResolvedValue([
      { message_id: 'm1', role: 'user', content: '帮我查天气', tool_calls: [], created_at: null },
      {
        message_id: 'm2', role: 'system', tool_calls: [], created_at: null,
        content: '会话已移交给专家「天气专家」，后续对话由其应答。',
        kind: 'handoff_notice', application_id: 'agent-1',
      },
      {
        message_id: 'm3', role: 'assistant', content: '', tool_calls: [], created_at: null,
        application_id: 'app-2',
      },
      {
        message_id: 'm4', role: 'assistant', content: '明天晴，20 度。', tool_calls: [],
        created_at: null, application_id: 'app-2',
      },
    ])

    const { result } = renderHook(() => useChatSession({ agentId: 'agent-1', flowType: 'agent' }))
    // 先让挂载期的会话列表刷新落地，selectConversation 才能从摘要重建发言权
    await act(async () => {})
    await act(async () => {
      await result.current.selectConversation('c1')
    })

    expect(result.current.activeHandoff).toEqual({
      applicationId: 'app-2', displayName: '天气专家',
    })
    expect(result.current.messages.map((item) => item.id)).toEqual(['m1', 'm2', 'm4'])
    expect(result.current.messages[1].handoffNotice).toContain('天气专家')
    expect(result.current.messages[2].answeredBy).toBe('天气专家')
  })

  it('会话列表透出接管标记（handoffAgent）', async () => {
    conversationList.mockResolvedValue([
      {
        conversation_id: 'c1', title: '查天气', created_at: null, updated_at: null,
        active_application_id: 'app-2', active_application: '天气专家',
      },
    ])

    const { result } = renderHook(() => useChatSession({ agentId: 'agent-1', flowType: 'agent' }))
    await act(async () => {})
    expect(result.current.conversationItems[0]).toMatchObject({
      id: 'c1', handoffAgent: '天气专家',
    })
  })

  it('停止生成后按会话摘要对齐发言权（断连窗内服务端已提交接管）', async () => {
    agentRun.mockImplementation(emitAgent([
      { event: 'run_start', data: { run_id: 'r1', tools: [] } },
      {
        event: 'result',
        data: { content: '移交完成', conversation_id: 'c1', finish_reason: 'handed_off' } as never,
      },
    ]))

    const { result } = renderHook(() => useChatSession({ agentId: 'agent-1', flowType: 'agent' }))
    await act(async () => {
      await result.current.send('查北京天气')
    })
    // 帧未送达（断连窗）时本地不发言权
    expect(result.current.activeHandoff).toBeNull()

    // 服务端摘要显示接管已提交：stop 后向事实对齐
    conversationList.mockResolvedValue([
      {
        conversation_id: 'c1', title: '查北京天气', created_at: null, updated_at: null,
        active_application_id: 'app-2', active_application: '天气专家',
      },
    ])
    await act(async () => {
      result.current.stop()
    })
    expect(result.current.activeHandoff).toEqual({
      applicationId: 'app-2', displayName: '天气专家',
    })
  })

  it('摘要窗口未含该会话时不清零发言权（批末 review #6：limit 外保留现态）', async () => {
    agentRun.mockImplementation(emitAgent([
      { event: 'run_start', data: { run_id: 'r1', tools: [] } },
      takeoverFrame,
      {
        event: 'result',
        data: { content: '', conversation_id: 'c1', finish_reason: 'handed_off' } as never,
      },
    ]))
    // 会话列表按 updated_at 取前 50 条：agent 通道不 touch updated_at，
    // 长期接管会话可能滑出窗口，find miss 不能当作"未接管"误清现态
    conversationList.mockResolvedValue([])

    const { result } = renderHook(() => useChatSession({ agentId: 'agent-1', flowType: 'agent' }))
    await act(async () => {
      await result.current.send('查北京天气')
    })
    expect(result.current.activeHandoff).toEqual({
      applicationId: 'app-2', displayName: '天气专家',
    })

    await act(async () => {
      result.current.stop()
    })
    expect(result.current.activeHandoff).toEqual({
      applicationId: 'app-2', displayName: '天气专家',
    })
  })
})
