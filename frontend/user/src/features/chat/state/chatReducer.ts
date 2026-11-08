import type {
  ActiveHandoff,
  ApprovalSpec,
  ChatMessage,
  PendingQuestion,
  PlanTask,
  ReflectNote,
  ToolTrace,
} from '../types'

export interface ChatState {
  messages: ChatMessage[]
  streaming: boolean
  conversationId: string | null
  threadId: string | null
  pendingQuestion: PendingQuestion | null
  /** 0074 PRD F10：最近一次挂起的工具审批（composer 提示与默认续跑目标） */
  pendingApproval: ApprovalSpec | null
  /** M4 PRD F14.10：当前发言权（非空=接管中，Composer 展示"返回主助手"） */
  activeHandoff: ActiveHandoff | null
}

export type ChatAction =
  | {
      type: 'start_run'
      userText: string
      userId: string
      assistantId?: string
      /** M4 PRD F14.10：接管轮的应答专家名（助手气泡徽标） */
      answeredBy?: string
    }
  | {
      type: 'retry_start'
      messages: ChatMessage[]
      assistantId: string
      /** M4 PRD F14.10：接管轮的应答专家名（助手气泡徽标） */
      answeredBy?: string
    }
  /** M4 PRD F14.10：handoff 帧/手动归位结果 → 通告气泡 + 发言权路由态 */
  | { type: 'handoff'; message: ChatMessage; active: ActiveHandoff | null }
  /** M4-c T-c9 冒烟修正：断连窗内本地未收帧但服务端可能已提交接管，按会话摘要对齐发言权 */
  | { type: 'set_active_handoff'; active: ActiveHandoff | null }
  | { type: 'append_assistant'; message: ChatMessage }
  | { type: 'append_tokens'; id: string; delta: string }
  | { type: 'llm_end'; id: string; content: string; streamed: boolean }
  | { type: 'tool_start'; id: string; trace: ToolTrace }
  | { type: 'tool_end'; id: string; trace: ToolTrace }
  | {
      type: 'agent_result'
      id: string
      content: string
      tools: ToolTrace[]
      notice?: string
      noticeTone?: 'waiting' | 'muted'
    }
  | { type: 'plan'; id: string; tasks: PlanTask[] }
  | { type: 'reflect'; id: string; note: ReflectNote }
  | { type: 'message_error'; id: string; message: string; detail?: string }
  | {
      type: 'question'
      message: ChatMessage
      pending: PendingQuestion
    }
  | { type: 'approval_interrupt'; message: ChatMessage }
  | { type: 'set_streaming'; streaming: boolean }
  | { type: 'stop'; id?: string }
  | { type: 'set_conversation'; conversationId: string | null }
  | { type: 'set_thread'; threadId: string | null }
  | {
      type: 'set_messages'
      messages: ChatMessage[]
      conversationId: string | null
      /** M4 PRD F14.10：切换会话时按会话摘要重建发言权（缺省=不在接管中） */
      activeHandoff?: ActiveHandoff | null
    }
  | { type: 'reset' }

export const initialChatState: ChatState = {
  messages: [],
  streaming: false,
  conversationId: null,
  threadId: null,
  pendingQuestion: null,
  pendingApproval: null,
  activeHandoff: null,
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
          ...(action.answeredBy ? { answeredBy: action.answeredBy } : {}),
        })
      }
      return {
        ...state,
        messages,
        streaming: true,
        pendingQuestion: null,
        // 新一轮开始即不再是"等待裁决"态；历史审批卡仍可按卡内 threadId 续跑
        pendingApproval: null,
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
            ...(action.answeredBy ? { answeredBy: action.answeredBy } : {}),
          },
        ],
        streaming: true,
        pendingQuestion: null,
        pendingApproval: null,
      }

    case 'handoff':
      return {
        ...state,
        messages: [...state.messages, action.message],
        activeHandoff: action.active,
      }

    case 'set_active_handoff':
      return { ...state, activeHandoff: action.active }

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
        // 0074 PRD F11：预算触顶等场景由上层传入提示，未传时保留原有 notice
        ...(action.notice !== undefined
          ? { notice: action.notice, noticeTone: action.noticeTone ?? message.noticeTone }
          : {}),
      }))

    case 'plan':
      return patchMessage(state, action.id, (message) => ({ ...message, plan: action.tasks }))

    case 'reflect':
      return patchMessage(state, action.id, (message) => {
        const rest = (message.reflects ?? []).filter((item) => item.round !== action.note.round)
        return { ...message, reflects: [...rest, action.note].sort((a, b) => a.round - b.round) }
      })

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

    case 'approval_interrupt': {
      const approval = action.message.approval ?? null
      return {
        ...state,
        messages: [...state.messages, action.message],
        pendingApproval: approval,
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
                !message.notice &&
                !message.plan?.length &&
                !message.reflects?.length
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
        pendingApproval: null,
        activeHandoff: action.activeHandoff ?? null,
        streaming: false,
      }

    case 'reset':
      return { ...initialChatState }

    default:
      return state
  }
}
