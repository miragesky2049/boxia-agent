import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import {
  runAgentStream,
  runChatflowStream,
  type AgentStreamEvent,
  type ChatflowStreamEvent,
  type ChatHistoryItem,
  type ToolCallTrace,
} from '../../../api/agentRun'
import {
  listConversationMessages,
  listConversations,
  type ConversationMessage,
  type ConversationSummary,
} from '../../../api/conversations'
import { chatReducer, initialChatState } from '../state/chatReducer'
import type { ChatMessage, ConversationItem, MessageError, ToolTrace } from '../types'

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
    name: trace.tool_name,
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
  flowType: 'workflow' | 'chatflow' | undefined
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

  const runAgent = useCallback(
    async (
      text: string,
      controller: AbortController,
      history: ChatHistoryItem[],
      assistantId: string,
    ) => {
      if (!agentId) return
      streamIdRef.current = assistantId

      try {
        await runAgentStream(
          agentId,
          {
            query: text,
            conversation_id: conversationIdRef.current ?? undefined,
            history,
          },
          (evt: AgentStreamEvent) => {
            switch (evt.event) {
              case 'llm_token':
                if (evt.data.delta) queueToken(evt.data.delta)
                break
              case 'llm_end':
                flushTokens()
                dispatch({
                  type: 'llm_end',
                  id: assistantId,
                  content: evt.data.content || '',
                  streamed: Boolean(evt.data.usage_streamed),
                })
                break
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
                dispatch({
                  type: 'agent_result',
                  id: assistantId,
                  content: evt.data.content,
                  tools: (evt.data.tool_traces || []).map(traceFromResult),
                })
                break
              }
              case 'error':
                flushTokens()
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
          dispatch({ type: 'stop', id: assistantId })
        } else {
          flushTokens()
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
        dispatch({ type: 'set_streaming', streaming: false })
        streamIdRef.current = null
        if (abortRef.current === controller) abortRef.current = null
      }
    },
    [agentId, flushTokens, queueToken, refreshConversations],
  )

  const send = useCallback(
    async (raw: string) => {
      const text = raw.trim()
      const snapshot = stateRef.current
      if (!text || snapshot.streaming || !agentId) return

      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      const answering = snapshot.pendingQuestion !== null
      const history = toHistoryItems(snapshot.messages)
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
      await runAgent(text, controller, history, assistantId)
    },
    [agentId, flowType, runAgent, runChatflow],
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
    const history = toHistoryItems(messages.slice(0, lastUserIndex))
    const assistantId = nextId()

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    dispatch({ type: 'retry_start', messages: kept, assistantId })
    await runAgent(lastUser.content, controller, history, assistantId)
  }, [agentId, flowType, runAgent])

  const stop = useCallback(() => {
    const snapshot = stateRef.current
    const controller = abortRef.current
    abortRef.current = null
    controller?.abort()
    flushTokens()
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
    selectConversation,
    newConversation,
    refreshConversations,
  }
}
