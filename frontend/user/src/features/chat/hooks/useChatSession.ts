import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import {
  runAgentStream,
  runChatflowStream,
  type AgentStreamEvent,
  type ChatflowStreamEvent,
  type ChatHistoryItem,
  type ToolChunkRef,
  type ToolCallTrace,
} from '../../../api/agentRun'
import {
  listConversationMessages,
  listConversations,
  type ConversationMessage,
  type ConversationSummary,
} from '../../../api/conversations'
import { chatReducer, initialChatState, type ChatAction } from '../state/chatReducer'
import type {
  ApprovalSpec,
  ChatMessage,
  ConversationItem,
  MessageError,
  PlanTask,
  ReflectNote,
  SourceChunk,
  ToolTrace,
} from '../types'

// 0074 PRD F3.5(c)：画布通道无 token 级流，最终回答整段到达后前端按打字机逐段输出
const TYPING_INTERVAL_MS = 33
const TYPING_TOTAL_TICKS = 45

type Dispatch = (action: ChatAction) => void

/**
 * 伪流式打字机：把一次性到达的完整文本按固定节拍 append_tokens。
 * finish 立即补齐剩余文本并收流；onDone 在收流后触发一次（用于延迟到
 * 打字结束再落定的 result 帧，避免整段正文瞬间覆盖打字机进度）。
 */
function createTypewriter(dispatch: Dispatch) {
  let id = ''
  let rest = ''
  let step = 1
  let timer: number | null = null
  let onDone: (() => void) | null = null

  const close = () => {
    const done = onDone
    onDone = null
    if (id) dispatch({ type: 'llm_end', id, content: '', streamed: true })
    id = ''
    rest = ''
    if (done) done()
  }

  const tick = () => {
    timer = null
    if (!id) return
    if (!rest) {
      close()
      return
    }
    const delta = rest.slice(0, step)
    rest = rest.slice(delta.length)
    dispatch({ type: 'append_tokens', id, delta })
    if (rest) timer = window.setTimeout(tick, TYPING_INTERVAL_MS)
    else close()
  }

  return {
    start(messageId: string, text: string) {
      // 上一段未播完先补齐，避免两条 llm_end 交错丢字
      this.finish()
      id = messageId
      rest = text
      step = Math.max(1, Math.ceil(text.length / TYPING_TOTAL_TICKS))
      timer = window.setTimeout(tick, TYPING_INTERVAL_MS)
    },
    isTyping(messageId: string): boolean {
      return id === messageId && (Boolean(rest) || timer !== null)
    },
    deferDone(callback: () => void) {
      onDone = callback
    },
    finish() {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
      if (id && rest) dispatch({ type: 'append_tokens', id, delta: rest })
      close()
    },
    /** 用户主动停止：只保留已播出部分，丢弃剩余与延迟落定的 result */
    halt() {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
      onDone = null
      rest = ''
      close()
    },
  }
}

function toSourceChunk(ref: ToolChunkRef): SourceChunk {
  return { datasetName: ref.dataset_name, chunkId: ref.chunk_id, score: ref.score, excerpt: ref.excerpt }
}

function toPlanTasks(
  tasks: Array<{ id?: string; goal?: string; acceptance?: string }> | undefined,
): PlanTask[] {
  return (tasks ?? [])
    .map((task) => ({ id: task.id, goal: String(task.goal ?? ''), acceptance: task.acceptance }))
    .filter((task) => task.goal)
}

let messageSeq = 0
function nextId(): string {
  messageSeq += 1
  return `msg_${Date.now()}_${messageSeq}`
}

function toMessageError(error: unknown, fallback: string): MessageError {
  // 断网/连接中断时 fetch 抛出 TypeError('Failed to fetch')，原文对用户没有意义
  if (error instanceof TypeError) {
    return { message: '网络连接中断，请检查网络后重试', detail: error.message }
  }
  return { message: error instanceof Error ? error.message : fallback }
}

function stringifyArgs(args: unknown): string | undefined {
  if (!args) return undefined
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return undefined
  }
}

function toHistoryItems(messages: ChatMessage[]): ChatHistoryItem[] {
  return messages
    .filter((message) => message.content && !message.error && !message.streaming)
    .slice(-20)
    .map((message) => ({ role: message.role, content: message.content }))
}

function traceFromResult(trace: ToolCallTrace): ToolTrace {
  return {
    id: trace.tool_call_id,
    name: trace.name,
    status: trace.is_error ? 'error' : 'done',
    args: stringifyArgs(trace.arguments),
    result: trace.observation || undefined,
  }
}

function historyToMessages(rows: ConversationMessage[]): ChatMessage[] {
  return rows
    .filter((row) => row.role === 'user' || row.role === 'assistant')
    .map((row) => {
      const tools =
        row.role === 'assistant' && row.tool_calls?.length
          ? row.tool_calls.map((call, index) => ({
              id: call.id ?? `hist_${row.message_id}_${index}`,
              name: call.name ?? 'tool',
              status: 'done' as const,
              args: call.arguments,
            }))
          : undefined
      return {
        id: row.message_id,
        role: row.role as 'user' | 'assistant',
        content: row.content,
        tools,
      }
    })
}

function extractOutputText(outputs: unknown): string {
  if (!outputs) return ''
  if (typeof outputs === 'string') return outputs
  if (typeof outputs === 'object') {
    const values = outputs as Record<string, unknown>
    const candidate = values.output ?? values.content
    if (typeof candidate === 'string') return candidate
  }
  return ''
}

export function formatConversationTime(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfYesterday = new Date(startOfToday)
  startOfYesterday.setDate(startOfYesterday.getDate() - 1)
  if (date >= startOfToday) {
    const hh = String(date.getHours()).padStart(2, '0')
    const mm = String(date.getMinutes()).padStart(2, '0')
    return `今天 ${hh}:${mm}`
  }
  if (date >= startOfYesterday) return '昨天'
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

interface UseChatSessionParams {
  agentId: string | undefined
  // 0074 PRD M3：agent 与旧聊天应用同源，统一走 /agents/{id}/chatflow/run/stream（服务端按 flow_type 分派）
  flowType: 'workflow' | 'chatflow' | 'agent' | undefined
}

export function useChatSession({ agentId, flowType }: UseChatSessionParams) {
  const [state, dispatch] = useReducer(chatReducer, initialChatState)
  const stateRef = useRef(state)
  stateRef.current = state

  const conversationIdRef = useRef<string | null>(null)
  const threadIdRef = useRef<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const tokenBufferRef = useRef('')
  const rafRef = useRef<number | null>(null)
  const streamIdRef = useRef<string | null>(null)
  const typewriterRef = useRef<ReturnType<typeof createTypewriter> | null>(null)
  if (!typewriterRef.current) {
    typewriterRef.current = createTypewriter(dispatch)
  }

  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [conversationsLoading, setConversationsLoading] = useState(false)

  const flushTokens = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    const delta = tokenBufferRef.current
    if (!delta) return
    tokenBufferRef.current = ''
    if (streamIdRef.current) {
      dispatch({ type: 'append_tokens', id: streamIdRef.current, delta })
    }
  }, [])

  const queueToken = useCallback(
    (delta: string) => {
      tokenBufferRef.current += delta
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(() => {
          rafRef.current = null
          flushTokens()
        })
      }
    },
    [flushTokens],
  )

  const refreshConversations = useCallback(async () => {
    if (!agentId) return
    setConversationsLoading(true)
    try {
      const list = await listConversations(agentId, { limit: 50 })
      setConversations(list)
    } catch (err) {
      console.error('加载会话列表失败', err)
    } finally {
      setConversationsLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    void refreshConversations()
  }, [refreshConversations])

  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
      typewriterRef.current?.finish()
    }
  }, [])

  const runChatflow = useCallback(
    async (text: string, answering: boolean, controller: AbortController) => {
      if (!agentId) return
      let emitted = 0
      try {
        await runChatflowStream(
          agentId,
          {
            message: answering ? '' : text,
            conversation_id: conversationIdRef.current ?? undefined,
            thread_id: threadIdRef.current ?? undefined,
            resume: answering ? { answer: text } : undefined,
          },
          (evt: ChatflowStreamEvent) => {
            switch (evt.event) {
              case 'run_start': {
                if (evt.data.conversation_id) {
                  conversationIdRef.current = evt.data.conversation_id
                  dispatch({ type: 'set_conversation', conversationId: evt.data.conversation_id })
                  void refreshConversations()
                }
                if (evt.data.thread_id) {
                  threadIdRef.current = evt.data.thread_id
                  dispatch({ type: 'set_thread', threadId: evt.data.thread_id })
                }
                break
              }
              case 'output_message': {
                const content = String(evt.data.content || '')
                if (content) {
                  emitted += 1
                  dispatch({
                    type: 'append_assistant',
                    message: { id: nextId(), role: 'assistant', content },
                  })
                }
                break
              }
              case 'question': {
                const question = String(evt.data.question || '请回答以下问题')
                const options = Array.isArray(evt.data.options)
                  ? evt.data.options.map((option) => String(option))
                  : []
                const threadId = String(evt.data.thread_id || '')
                if (threadId) {
                  threadIdRef.current = threadId
                  dispatch({ type: 'set_thread', threadId })
                }
                dispatch({
                  type: 'question',
                  message: {
                    id: nextId(),
                    role: 'assistant',
                    content: question,
                    question: { text: question, options },
                  },
                  pending: {
                    text: question,
                    options,
                    threadId,
                    runId: String(evt.data.run_id || ''),
                  },
                })
                break
              }
              case 'result': {
                if (emitted === 0) {
                  const content = extractOutputText(evt.data.outputs)
                  if (content) {
                    dispatch({
                      type: 'append_assistant',
                      message: { id: nextId(), role: 'assistant', content },
                    })
                  }
                }
                void refreshConversations()
                break
              }
              case 'interrupted':
                dispatch({
                  type: 'append_assistant',
                  message: {
                    id: nextId(),
                    role: 'assistant',
                    content: '',
                    notice: '流程等待人工审批，请联系管理员处理后再继续。',
                  },
                })
                break
              case 'error':
                dispatch({
                  type: 'append_assistant',
                  message: {
                    id: nextId(),
                    role: 'assistant',
                    content: '',
                    error: { message: evt.data.message || '对话流运行失败' },
                  },
                })
                break
              default:
                break
            }
          },
          { signal: controller.signal },
        )
      } catch (err) {
        if (!controller.signal.aborted) {
          dispatch({
            type: 'append_assistant',
            message: {
              id: nextId(),
              role: 'assistant',
              content: '',
              error: toMessageError(err, '调用对话流失败'),
            },
          })
        }
      } finally {
        dispatch({ type: 'set_streaming', streaming: false })
        if (abortRef.current === controller) abortRef.current = null
      }
    },
    [agentId, refreshConversations],
  )

  interface AgentRunInput {
    text: string
    controller: AbortController
    history: ChatHistoryItem[] | undefined
    assistantId: string
    /** 0074 PRD F9：随消息携带的图片 URL */
    images?: string[]
    /** 0074 PRD F10：审批裁决续跑 */
    resume?: Record<string, unknown>
    threadId?: string
  }

  const runAgent = useCallback(
    async (input: AgentRunInput) => {
      if (!agentId) return
      const { text, controller, history, assistantId } = input
      streamIdRef.current = assistantId

      try {
        await runAgentStream(
          agentId,
          {
            message: text,
            conversation_id: conversationIdRef.current ?? undefined,
            history,
            images: input.images,
            resume: input.resume,
            thread_id: input.threadId,
          },
          (evt: AgentStreamEvent) => {
            switch (evt.event) {
              case 'llm_token':
                if (evt.data.delta) queueToken(evt.data.delta)
                break
              case 'llm_end':
                flushTokens()
                if (!evt.data.usage_streamed && evt.data.content) {
                  // 0074 PRD F3.5(c)：画布通道整段正文 → 打字机逐段输出
                  typewriterRef.current?.start(assistantId, evt.data.content)
                } else {
                  dispatch({
                    type: 'llm_end',
                    id: assistantId,
                    content: evt.data.content || '',
                    streamed: Boolean(evt.data.usage_streamed),
                  })
                }
                break
              case 'plan':
                dispatch({ type: 'plan', id: assistantId, tasks: toPlanTasks(evt.data.tasks) })
                break
              case 'reflect': {
                const note: ReflectNote = {
                  round: evt.data.reflect_round || (stateRef.current.messages.find((m) => m.id === assistantId)?.reflects?.length ?? 0) + 1,
                  done: Boolean(evt.data.done),
                  critique: evt.data.critique || undefined,
                  suggestion: evt.data.suggestion || undefined,
                }
                dispatch({ type: 'reflect', id: assistantId, note })
                break
              }
              case 'tool_start':
                dispatch({
                  type: 'tool_start',
                  id: assistantId,
                  trace: {
                    id: evt.data.tool_call_id,
                    name: evt.data.name,
                    status: 'running',
                    args: stringifyArgs(evt.data.arguments),
                  },
                })
                break
              case 'tool_end':
                dispatch({
                  type: 'tool_end',
                  id: assistantId,
                  trace: {
                    id: evt.data.tool_call_id,
                    name: evt.data.name,
                    status: evt.data.is_error ? 'error' : 'done',
                    result: evt.data.observation,
                    // 0074 PRD F5.3：检索工具的引用来源（additive，无则不带键）
                    ...(evt.data.chunks?.length ? { chunks: evt.data.chunks.map(toSourceChunk) } : {}),
                  },
                })
                break
              case 'result': {
                flushTokens()
                const conversationId = evt.data.conversation_id
                if (conversationId) {
                  conversationIdRef.current = conversationId
                  dispatch({ type: 'set_conversation', conversationId })
                }
                void refreshConversations()
                // 后端 result.tool_traces 无 chunks，按 tool_call_id 保留流内已展示的来源
                const previous = stateRef.current.messages.find((message) => message.id === assistantId)
                const chunksById = new Map(
                  (previous?.tools ?? [])
                    .filter((tool) => tool.chunks?.length)
                    .map((tool) => [tool.id, tool.chunks] as const),
                )
                const tools = (evt.data.tool_traces || []).map((trace) => {
                  const item = traceFromResult(trace)
                  const chunks = chunksById.get(item.id)
                  return chunks ? { ...item, chunks } : item
                })
                const settle: ChatAction = {
                  type: 'agent_result',
                  id: assistantId,
                  content: evt.data.content,
                  tools,
                  // 0074 PRD F11.1：预算触顶时提示收敛原因（其他 finish_reason 不提示）
                  ...(evt.data.finish_reason === 'budget_exceeded'
                    ? { notice: '已达到本轮 Token 预算上限，回答基于已有工具结果收敛。', noticeTone: 'muted' as const }
                    : {}),
                }
                const typewriter = typewriterRef.current
                if (typewriter && typewriter.isTyping(assistantId)) {
                  // 打字机播完再落定 result，避免整段正文瞬间覆盖打字进度
                  typewriter.deferDone(() => dispatch(settle))
                } else {
                  dispatch(settle)
                }
                break
              }
              case 'interrupted': {
                // 0074 PRD F10：敏感工具挂起。当前气泡保留已执行的工具轨迹后收流，
                // 另起一条带审批卡的气泡等待用户裁决（审批卡自带续跑坐标）
                flushTokens()
                typewriterRef.current?.finish()
                dispatch({ type: 'llm_end', id: assistantId, content: '', streamed: true })
                const calls = (evt.data.approval?.awaiting_calls ?? []).map((call) => ({
                  id: call.id,
                  name: call.name,
                  arguments: call.arguments,
                }))
                if (evt.data.conversation_id) {
                  conversationIdRef.current = evt.data.conversation_id
                  dispatch({ type: 'set_conversation', conversationId: evt.data.conversation_id })
                }
                dispatch({
                  type: 'approval_interrupt',
                  message: {
                    id: nextId(),
                    role: 'assistant',
                    content: '',
                    approval: {
                      calls,
                      threadId: evt.data.thread_id || '',
                      runId: evt.data.run_id || '',
                    },
                  },
                })
                void refreshConversations()
                break
              }
              case 'error':
                flushTokens()
                typewriterRef.current?.finish()
                dispatch({
                  type: 'message_error',
                  id: assistantId,
                  message: evt.data.message || '运行失败',
                })
                break
              default:
                break
            }
          },
          { signal: controller.signal },
        )
      } catch (err) {
        if (controller.signal.aborted) {
          typewriterRef.current?.halt()
          dispatch({ type: 'stop', id: assistantId })
        } else {
          flushTokens()
          typewriterRef.current?.finish()
          const error = toMessageError(err, '调用智能体失败')
          dispatch({
            type: 'message_error',
            id: assistantId,
            message: error.message,
            detail: error.detail,
          })
        }
      } finally {
        flushTokens()
        // 打字机不在此收流：画布通道 result 帧紧跟 llm_end，正文靠 setTimeout 继续播放，
        // 自然播完由 close() 落定（deferred result 回调见 result 分支）
        dispatch({ type: 'set_streaming', streaming: false })
        streamIdRef.current = null
        if (abortRef.current === controller) abortRef.current = null
      }
    },
    [agentId, flushTokens, queueToken, refreshConversations],
  )

  const send = useCallback(
    async (raw: string, images?: string[]) => {
      const text = raw.trim()
      const snapshot = stateRef.current
      if (!text || snapshot.streaming || !agentId) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const answering = snapshot.pendingQuestion !== null
      // 0074 PRD F8：agent 型省略 history，启用服务端记忆（undefined≠[]）；
      // 旧聊天应用继续前端携带历史
      const history = flowType === 'agent' ? undefined : toHistoryItems(snapshot.messages)
      const assistantId = nextId()
      dispatch({
        type: 'start_run',
        userText: text,
        userId: nextId(),
        assistantId: flowType === 'chatflow' ? undefined : assistantId,
      })

      if (flowType === 'chatflow') {
        await runChatflow(text, answering, controller)
        return
      }
      await runAgent({ text, controller, history, assistantId, images })
    },
    [agentId, flowType, runAgent, runChatflow],
  )

  /** 0074 PRD F10：审批裁决续跑（target 缺省取最近一次挂起） */
  const resolveApproval = useCallback(
    async (approved: boolean, comment: string, target?: ApprovalSpec) => {
      const snapshot = stateRef.current
      const approval = target ?? snapshot.pendingApproval
      if (!agentId || snapshot.streaming || !approval) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      // 与后端 _approval_decision_text 同构，保证会话气泡文案与落库消息一致
      const base = approved ? '批准执行工具调用' : '拒绝执行工具调用'
      const decisionText = comment ? `${base}（理由：${comment}）` : base
      const assistantId = nextId()
      dispatch({ type: 'start_run', userText: decisionText, userId: nextId(), assistantId })

      // 续跑：快照自带执行现场，不带历史；message 留空由后端生成裁决文案
      await runAgent({
        text: '',
        controller,
        history: [],
        assistantId,
        resume: { approved, comment },
        threadId: approval.threadId,
      })
    },
    [agentId, runAgent],
  )

  const retry = useCallback(async () => {
    const snapshot = stateRef.current
    if (!agentId || snapshot.streaming || flowType === 'chatflow') return
    const messages = snapshot.messages
    let lastUserIndex = -1
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'user') {
        lastUserIndex = index
        break
      }
    }
    if (lastUserIndex < 0) return
    const lastUser = messages[lastUserIndex]
    const kept = messages.slice(0, lastUserIndex + 1)
    const history =
      flowType === 'agent' ? undefined : toHistoryItems(messages.slice(0, lastUserIndex))
    const assistantId = nextId()

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    dispatch({ type: 'retry_start', messages: kept, assistantId })
    await runAgent({ text: lastUser.content, controller, history, assistantId })
  }, [agentId, flowType, runAgent])

  const stop = useCallback(() => {
    const snapshot = stateRef.current
    const controller = abortRef.current
    abortRef.current = null
    controller?.abort()
    flushTokens()
    typewriterRef.current?.halt()
    dispatch({ type: 'stop', id: streamIdRef.current ?? undefined })
    dispatch({ type: 'set_streaming', streaming: false })
    const last = snapshot.messages[snapshot.messages.length - 1]
    if (flowType === 'chatflow' && last?.role === 'user') {
      dispatch({
        type: 'append_assistant',
        message: {
          id: nextId(),
          role: 'assistant',
          content: '',
          notice: '已停止生成',
          noticeTone: 'muted',
        },
      })
    }
  }, [flushTokens, flowType])

  const selectConversation = useCallback(
    async (conversationId: string) => {
      if (!agentId || conversationId === conversationIdRef.current) return
      if (stateRef.current.streaming) return
      setConversationsLoading(true)
      try {
        const rows = await listConversationMessages(agentId, conversationId)
        conversationIdRef.current = conversationId
        threadIdRef.current = null
        dispatch({
          type: 'set_messages',
          messages: historyToMessages(rows),
          conversationId,
        })
      } catch (err) {
        console.error('加载历史消息失败', err)
      } finally {
        setConversationsLoading(false)
      }
    },
    [agentId],
  )

  const newConversation = useCallback(() => {
    if (stateRef.current.streaming) return
    abortRef.current?.abort()
    abortRef.current = null
    conversationIdRef.current = null
    threadIdRef.current = null
    dispatch({ type: 'reset' })
  }, [])

  const conversationItems: ConversationItem[] = useMemo(
    () =>
      conversations.map((item) => ({
        id: item.conversation_id,
        title: item.title || '未命名会话',
        updatedAt: formatConversationTime(item.updated_at),
      })),
    [conversations],
  )

  return {
    ...state,
    conversationItems,
    conversationsLoading,
    send,
    stop,
    retry,
    resolveApproval,
    selectConversation,
    newConversation,
    refreshConversations,
  }
}
