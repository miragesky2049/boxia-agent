import { describe, expect, it } from 'vitest'
import { chatReducer, initialChatState, type ChatState } from './chatReducer'

function stateWithAssistant(content = ''): ChatState {
  return {
    ...initialChatState,
    streaming: true,
    messages: [
      { id: 'u1', role: 'user', content: '你好' },
      { id: 'a1', role: 'assistant', content, streaming: true },
    ],
  }
}

describe('chatReducer', () => {
  it('start_run 追加用户消息并为智能体流程预留助手占位', () => {
    const next = chatReducer(initialChatState, {
      type: 'start_run',
      userText: '你好',
      userId: 'u1',
      assistantId: 'a1',
    })
    expect(next.messages.map((item) => item.id)).toEqual(['u1', 'a1'])
    expect(next.messages[1]).toMatchObject({ role: 'assistant', streaming: true })
    expect(next.streaming).toBe(true)
  })

  it('对话流 start_run 不预留助手占位', () => {
    const next = chatReducer(initialChatState, {
      type: 'start_run',
      userText: '你好',
      userId: 'u1',
    })
    expect(next.messages).toHaveLength(1)
    expect(next.messages[0].role).toBe('user')
  })

  it('llm_end 在未流式输出时整体覆盖内容', () => {
    const next = chatReducer(stateWithAssistant('流式片段'), {
      type: 'llm_end',
      id: 'a1',
      content: '完整回复',
      streamed: false,
    })
    expect(next.messages[1]).toMatchObject({ content: '完整回复', streaming: false })
  })

  it('llm_end 在已流式输出时保留增量内容', () => {
    const next = chatReducer(stateWithAssistant('流式片段'), {
      type: 'llm_end',
      id: 'a1',
      content: '完整回复',
      streamed: true,
    })
    expect(next.messages[1].content).toBe('流式片段')
    expect(next.messages[1].streaming).toBe(false)
  })

  it('agent_result 覆盖内容与工具轨迹', () => {
    const next = chatReducer(stateWithAssistant('半截'), {
      type: 'agent_result',
      id: 'a1',
      content: '最终答案',
      tools: [{ id: 't1', name: 'search', status: 'done', result: 'ok' }],
    })
    expect(next.messages[1]).toMatchObject({ content: '最终答案', streaming: false })
    expect(next.messages[1].tools).toHaveLength(1)
  })

  it('tool_end 按 tool_call_id 合并同一轨迹', () => {
    const started = chatReducer(stateWithAssistant(), {
      type: 'tool_start',
      id: 'a1',
      trace: { id: 't1', name: 'search', status: 'running', args: '{}' },
    })
    const ended = chatReducer(started, {
      type: 'tool_end',
      id: 'a1',
      trace: { id: 't1', name: 'search', status: 'done', result: 'ok' },
    })
    expect(ended.messages[1].tools).toEqual([
      { id: 't1', name: 'search', status: 'done', result: 'ok' },
    ])
  })

  it('question 提交旧问题并登记待回答状态，回答后清除', () => {
    const asked = chatReducer(stateWithAssistant('请选择'), {
      type: 'question',
      message: {
        id: 'q1',
        role: 'assistant',
        content: '请选择',
        question: { text: '请选择', options: ['A', 'B'] },
      },
      pending: { text: '请选择', options: ['A', 'B'], threadId: 'th1', runId: 'r1' },
    })
    expect(asked.pendingQuestion?.threadId).toBe('th1')
    expect(asked.messages).toHaveLength(3)

    const answered = chatReducer(asked, {
      type: 'start_run',
      userText: 'A',
      userId: 'u2',
    })
    expect(answered.pendingQuestion).toBeNull()
    expect(answered.messages[2].question?.submitted).toBe(true)
    expect(answered.messages[3]).toMatchObject({ role: 'user', content: 'A' })
  })

  it('plan/reflect 累积深度模式进展（0074 PRD F4）', () => {
    const planned = chatReducer(stateWithAssistant(''), {
      type: 'plan',
      id: 'a1',
      tasks: [{ goal: '查订单' }, { goal: '发起退款' }],
    })
    expect(planned.messages[1].plan).toHaveLength(2)
    const reflected = chatReducer(planned, {
      type: 'reflect',
      id: 'a1',
      note: { round: 1, done: false, critique: '缺少单号' },
    })
    const reflected2 = chatReducer(reflected, {
      type: 'reflect',
      id: 'a1',
      note: { round: 1, done: true },
    })
    // 同轮次覆盖而非追加
    expect(reflected2.messages[1].reflects).toEqual([{ round: 1, done: true }])
  })

  it('stop 保留仅含 plan 的气泡', () => {
    const planned = chatReducer(stateWithAssistant(''), { type: 'plan', id: 'a1', tasks: [{ goal: 'g' }] })
    const next = chatReducer(planned, { type: 'stop', id: 'a1' })
    expect(next.messages.map((item) => item.id)).toEqual(['u1', 'a1'])
  })

  it('agent_result 传入 notice 覆盖、缺省保留（0074 PRD F11）', () => {
    const budgeted = chatReducer(stateWithAssistant('草稿'), {
      type: 'agent_result',
      id: 'a1',
      content: '最终回答',
      tools: [],
      notice: '已达到本轮 Token 预算上限',
      noticeTone: 'muted',
    })
    expect(budgeted.messages[1]).toMatchObject({
      content: '最终回答',
      notice: '已达到本轮 Token 预算上限',
      noticeTone: 'muted',
    })
    const plain = chatReducer(budgeted, { type: 'agent_result', id: 'a1', content: 'v2', tools: [] })
    expect(plain.messages[1].notice).toBe('已达到本轮 Token 预算上限')
  })

  it('stop 结束流式状态', () => {
    const next = chatReducer(stateWithAssistant('片段'), { type: 'stop', id: 'a1' })
    expect(next.streaming).toBe(false)
    expect(next.messages[1].streaming).toBe(false)
    expect(next.messages[1].content).toBe('片段')
  })

  it('stop 移除尚未产出内容的空占位气泡', () => {
    const next = chatReducer(stateWithAssistant(''), { type: 'stop', id: 'a1' })
    expect(next.messages.map((item) => item.id)).toEqual(['u1'])
  })

  it('set_messages 清空待回答问题与线程状态', () => {
    const asked = chatReducer(stateWithAssistant(), {
      type: 'question',
      message: {
        id: 'q1',
        role: 'assistant',
        content: '请选择',
        question: { text: '请选择', options: [] },
      },
      pending: { text: '请选择', options: [], threadId: 'th1', runId: 'r1' },
    })
    const next = chatReducer(asked, {
      type: 'set_messages',
      messages: [{ id: 'h1', role: 'user', content: '历史' }],
      conversationId: 'c1',
    })
    expect(next.messages).toHaveLength(1)
    expect(next.pendingQuestion).toBeNull()
    expect(next.threadId).toBeNull()
    expect(next.conversationId).toBe('c1')
  })

  it('0074 F10：approval_interrupt 追加审批卡并登记 pendingApproval', () => {
    const next = chatReducer(stateWithAssistant(''), {
      type: 'approval_interrupt',
      message: {
        id: 'ap1',
        role: 'assistant',
        content: '',
        approval: { calls: [{ id: 'c1', name: 'send_email' }], threadId: 'c1:sub', runId: 'r1' },
      },
    })
    expect(next.messages.map((item) => item.id)).toEqual(['u1', 'a1', 'ap1'])
    expect(next.pendingApproval).toMatchObject({ threadId: 'c1:sub', runId: 'r1' })
  })

  it('0074 F10：新一轮开始清空 pendingApproval（历史审批卡仍可单独续跑）', () => {
    const withApproval: ChatState = {
      ...initialChatState,
      messages: [{
        id: 'ap1', role: 'assistant', content: '',
        approval: { calls: [], threadId: 't1', runId: 'r1' },
      }],
      pendingApproval: { calls: [], threadId: 't1', runId: 'r1' },
    }
    const next = chatReducer(withApproval, {
      type: 'start_run', userText: '换个话题', userId: 'u2',
    })
    expect(next.pendingApproval).toBeNull()
    expect(next.messages.find((item) => item.id === 'ap1')?.approval).toBeTruthy()
  })

  it('0074 F10：set_messages/reset 同步清空 pendingApproval', () => {
    const withApproval: ChatState = {
      ...initialChatState,
      pendingApproval: { calls: [], threadId: 't1', runId: 'r1' },
    }
    expect(chatReducer(withApproval, { type: 'reset' }).pendingApproval).toBeNull()
    const loaded = chatReducer(withApproval, {
      type: 'set_messages', messages: [], conversationId: 'c9',
    })
    expect(loaded.pendingApproval).toBeNull()
  })

  describe('M4 F14.10 接管发言权路由态', () => {
    it('handoff 接管帧：追加通告气泡并登记 activeHandoff', () => {
      const next = chatReducer(initialChatState, {
        type: 'handoff',
        message: {
          id: 'n1', role: 'assistant', content: '',
          handoffNotice: '会话已移交给专家「天气专家」，后续对话由其应答。',
        },
        active: { applicationId: 'app-2', displayName: '天气专家' },
      })
      expect(next.activeHandoff).toEqual({ applicationId: 'app-2', displayName: '天气专家' })
      expect(next.messages).toHaveLength(1)
      expect(next.messages[0].handoffNotice).toContain('天气专家')
    })

    it('handoff 归位帧：通告气泡并清空发言权', () => {
      const takenOver = chatReducer(initialChatState, {
        type: 'handoff',
        message: { id: 'n1', role: 'assistant', content: '', handoffNotice: '移交' },
        active: { applicationId: 'app-2', displayName: '天气专家' },
      })
      const next = chatReducer(takenOver, {
        type: 'handoff',
        message: {
          id: 'n2', role: 'assistant', content: '',
          handoffNotice: '接管已结束，会话已归位主助手「主助手」。',
        },
        active: null,
      })
      expect(next.activeHandoff).toBeNull()
      expect(next.messages.map((item) => item.id)).toEqual(['n1', 'n2'])
    })

    it('start_run 的 answeredBy 挂到助手占位气泡（接管轮由专家应答徽标）', () => {
      const next = chatReducer(initialChatState, {
        type: 'start_run', userText: '明天穿什么', userId: 'u1', assistantId: 'a1',
        answeredBy: '天气专家',
      })
      expect(next.messages[1]).toMatchObject({ id: 'a1', answeredBy: '天气专家' })
      expect(next.messages[0].answeredBy).toBeUndefined()
    })

    it('set_messages 切会话携带 activeHandoff，缺省清空；reset 清空', () => {
      const takenOver: ChatState = {
        ...initialChatState,
        activeHandoff: { applicationId: 'app-2', displayName: '天气专家' },
      }
      const switched = chatReducer(takenOver, {
        type: 'set_messages', messages: [], conversationId: 'c9',
        activeHandoff: { applicationId: 'app-3', displayName: '合同专家' },
      })
      expect(switched.activeHandoff).toEqual({ applicationId: 'app-3', displayName: '合同专家' })
      const plain = chatReducer(takenOver, {
        type: 'set_messages', messages: [], conversationId: 'c8',
      })
      expect(plain.activeHandoff).toBeNull()
      expect(chatReducer(takenOver, { type: 'reset' }).activeHandoff).toBeNull()
    })

    it('set_active_handoff 仅对齐发言权，不动消息与其他状态', () => {
      const base = chatReducer(initialChatState, {
        type: 'start_run',
        assistantId: 'a1',
        userId: 'u1',
        userText: '查天气',
      })
      const next = chatReducer(base, {
        type: 'set_active_handoff',
        active: { applicationId: 'app-2', displayName: '天气专家' },
      })
      expect(next.activeHandoff).toEqual({ applicationId: 'app-2', displayName: '天气专家' })
      expect(next.messages).toBe(base.messages)
      const cleared = chatReducer(next, { type: 'set_active_handoff', active: null })
      expect(cleared.activeHandoff).toBeNull()
    })
  })
})
