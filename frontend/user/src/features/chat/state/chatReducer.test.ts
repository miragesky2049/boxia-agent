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
})
