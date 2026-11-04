import type { ChatMessage, PendingQuestion, ToolTrace } from '../types'

export interface ChatState {
  messages: ChatMessage[]
  streaming: boolean
  conversationId: string | null
  threadId: string | null
  pendingQuestion: PendingQuestion | null
}

export type ChatAction =
  | {
      type: 'start_run'
      userText: string
      userId: string
      assistantId?: string
    }
  | { type: 'retry_start'; messages: ChatMessage[]; assistantId: string }
  | { type: 'append_assistant'; message: ChatMessage }
  | { type: 'append_tokens'; id: string; delta: string }
  | { type: 'llm_end'; id: string; content: string; streamed: boolean }
  | { type: 'tool_start'; id: string; trace: ToolTrace }
  | { type: 'tool_end'; id: string; trace: ToolTrace }
  | { type: 'agent_result'; id: string; content: string; tools: ToolTrace[] }
  | { type: 'message_error'; id: string; message: string; detail?: string }
  | {
      type: 'question'
      message: ChatMessage
      pending: PendingQuestion
    }
  | { type: 'set_streaming'; streaming: boolean }
  | { type: 'stop'; id?: string }
  | { type: 'set_conversation'; conversationId: string | null }
  | { type: 'set_thread'; threadId: string | null }
  | { type: 'set_messages'; messages: ChatMessage[]; conversationId: string | null }
  | { type: 'reset' }

export const initialChatState: ChatState = {
  messages: [],
  streaming: false,
  conversationId: null,
  threadId: null,
  pendingQuestion: null,
}

function patchMessage(
  state: ChatState,
  id: string,
  patch: (message: ChatMessage) => ChatMessage,
): ChatState {
  return {
    ...state,
    messages: state.messages.map((message) => (message.id === id ? patch(message) : message)),
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'start_run': {
      const messages: ChatMessage[] = [
        ...state.messages.map((message) =>
          message.question && !message.question.submitted
            ? { ...message, question: { ...message.question, submitted: true } }
            : message,
        ),
        { id: action.userId, role: 'user', content: action.userText },
      ]
      if (action.assistantId) {
        messages.push({
          id: action.assistantId,
          role: 'assistant',
          content: '',
          streaming: true,
        })
      }
      return {
        ...state,
        messages,
        streaming: true,
        pendingQuestion: null,
      }
    }

    case 'retry_start':
      return {
        ...state,
        messages: [
          ...action.messages,
          {
            id: action.assistantId,
            role: 'assistant',
            content: '',
            streaming: true,
          },
        ],
        streaming: true,
        pendingQuestion: null,
      }

    case 'append_assistant':
      return { ...state, messages: [...state.messages, action.message] }

    case 'append_tokens':
      return patchMessage(state, action.id, (message) => ({
        ...message,
        streaming: true,
        content: message.content + action.delta,
      }))

    case 'llm_end':
      return patchMessage(state, action.id, (message) => {
        // 非流式回退：llm_end.content 是本轮完整输出，需要整体覆盖
        const content =
          action.content && !action.streamed ? action.content : message.content
        return { ...message, content, streaming: false }
      })

    case 'tool_start':
      return patchMessage(state, action.id, (message) => ({
        ...message,
        tools: [...(message.tools ?? []), action.trace],
      }))

    case 'tool_end':
      return patchMessage(state, action.id, (message) => {
        const tools = message.tools ?? []
        const exists = tools.some((trace) => trace.id === action.trace.id)
        return {
          ...message,
          tools: exists
            ? tools.map((trace) => (trace.id === action.trace.id ? action.trace : trace))
            : [...tools, action.trace],
        }
      })

    case 'agent_result':
      return patchMessage(state, action.id, (message) => ({
        ...message,
        content: action.content,
        tools: action.tools,
        streaming: false,
      }))

    case 'message_error':
      return patchMessage(state, action.id, (message) => ({
        ...message,
        streaming: false,
        error: { message: action.message, detail: action.detail },
      }))

    case 'question': {
      const messages = state.messages.map((message) =>
        message.question && !message.question.submitted
          ? { ...message, question: { ...message.question, submitted: true } }
          : message,
      )
      return {
        ...state,
        messages: [...messages, action.message],
        pendingQuestion: action.pending,
      }
    }

    case 'set_streaming':
      return { ...state, streaming: action.streaming }

    case 'stop': {
      const stoppedIds = new Set(
        state.messages
          .filter(
            (message) =>
              message.id === action.id ||
              (action.id === undefined && message.streaming),
          )
          .map((message) => message.id),
      )
      return {
        ...state,
        streaming: false,
        messages: state.messages
          .map((message) =>
            stoppedIds.has(message.id) ? { ...message, streaming: false } : message,
          )
          // 中止时尚未产出任何内容的气泡没有展示价值，直接移除
          .filter(
            (message) =>
              !(
                stoppedIds.has(message.id) &&
                !message.content &&
                !message.tools?.length &&
                !message.error &&
                !message.question &&
                !message.notice
              ),
          ),
      }
    }

    case 'set_conversation':
      return { ...state, conversationId: action.conversationId }

    case 'set_thread':
      return { ...state, threadId: action.threadId }

    case 'set_messages':
      return {
        ...state,
        messages: action.messages,
        conversationId: action.conversationId,
        threadId: null,
        pendingQuestion: null,
        streaming: false,
      }

    case 'reset':
      return { ...initialChatState }

    default:
      return state
  }
}
