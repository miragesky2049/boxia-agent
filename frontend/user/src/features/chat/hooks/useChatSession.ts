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
  ActiveHandoff,
  ApprovalSpec,
  ChatMessage,
  ConversationItem,
  MessageError,
  PlanTask,
  ReflectNote,
  SourceChunk,
  ToolTrace,
} from '../types'

/** M4 PRD F14.10：SSE handoff 帧载荷（移交/归位两用，returned 区分） */
type HandoffFrame = Extract<AgentStreamEvent, { event: 'handoff' }>['data']

// 通告文案与后端 chat_service system 行逐字一致，保证 live 帧与历史回放渲染同一气泡
function handoffNoticeText(frame: Pick<HandoffFrame, 'display_name' | 'returned'>): string {
  return frame.returned
    ? `接管已结束，会话已归位主助手「${frame.display_name}」。`
    : `会话已移交给专家「${frame.display_name}」，后续对话由其应答。`
}

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

function historyToMessages(
  rows: ConversationMessage[],
  ownerApplicationId: string,
  activeHandoff: ActiveHandoff | null,
): ChatMessage[] {
  const messages: ChatMessage[] = []
  for (const row of rows) {
    if (row.role === 'system') {
      // M4 PRD F14.10/11：后端只放行 kind=handoff_notice 通告行，重建居中转接气泡
      if (row.kind === 'handoff_notice') {
        messages.push({
          id: row.message_id,
          role: 'assistant',
          content: '',
          handoffNotice: row.content,
        })
      }
      continue
    }
    if (row.role !== 'user' && row.role !== 'assistant') continue
    const tools =
      row.role === 'assistant' && row.tool_calls?.length
        ? row.tool_calls.map((call, index) => ({
            id: call.id ?? `hist_${row.message_id}_${index}`,
            name: call.name ?? 'tool',
            status: 'done' as const,
            args: call.arguments,
          }))
        : undefined
    // 接管轮助手空正文行仅承载 run 归因，历史回放无展示价值
    if (row.role === 'assistant' && !row.content && !tools?.length) continue
    const answeredBy =
      row.role === 'assistant' && row.application_id && row.application_id !== ownerApplicationId
        ? (activeHandoff && row.application_id === activeHandoff.applicationId
            ? activeHandoff.displayName
            : '专家')
        : undefined
    messages.push({
      id: row.message_id,
      role: row.role,
      content: row.content,
      tools,
      ...(answeredBy ? { answeredBy } : {}),
    })
  }
  return messages
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

  const fetchConversations = useCallback(async (): Promise<ConversationSummary[]> => {
    if (!agentId) return []
    return await listConversations(agentId, { limit: 50 })
  }, [agentId])

  const refreshConversations = useCallback(async () => {
    if (!agentId) return
    setConversationsLoading(true)
    try {
      setConversations(await fetchConversations())
    } catch (err) {
      console.error('加载会话列表失败', err)
    } finally {
      setConversationsLoading(false)
    }
  }, [agentId, fetchConversations])

  /**
   * M4-c T-c9 冒烟修正：停止生成/断连后按服务端会话摘要对齐发言权。
   * handoff 帧可能在断连窗内丢失，而服务端接管仅在 run 成功提交后生效（T-c5 口径），
   * 以摘要为事实重建 activeHandoff，避免"专家应答中但 UI 无归位入口"的悬挂态。
   */
  const syncHandoffFromSummary = useCallback(() => {
    const cid = conversationIdRef.current
    if (!cid) return
    void fetchConversations()
      .then((list) => {
        setConversations(list)
        const summary = list.find((item) => item.conversation_id === cid)
        // 批末 review #6：列表只取最近更新的前 50 条，agent 通道不 touch updated_at，
        // 长期接管会话可能滑出窗口；miss 时不能误判为"未接管"，保留现态待命中收敛
        if (!summary) return
        dispatch({
          type: 'set_active_handoff',
          active:
            summary.active_application_id != null
              ? {
                  applicationId: summary.active_application_id,
                  displayName: summary.active_application ?? '',
                }
              : null,
        })
      })
      .catch((err: unknown) => {
        console.error('对齐接管路由态失败', err)
      })
  }, [fetchConversations])

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

  /** M4 PRD F14.10：handoff 帧统一处理——追加通告气泡、维护发言权，并刷新侧栏接管标记 */
  const applyHandoffFrame = useCallback(
    (frame: HandoffFrame) => {
      dispatch({
        type: 'handoff',
        message: {
          id: nextId(),
          role: 'assistant',
          content: '',
          handoffNotice: handoffNoticeText(frame),
        },
        active: frame.returned
          ? null
          : { applicationId: frame.to_app_id, displayName: frame.display_name },
      })
      void refreshConversations()
    },
    [refreshConversations],
  )

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
              case 'handoff':
                applyHandoffFrame(evt.data)
                break
              case 'result': {
                flushTokens()
                const conversationId = evt.data.conversation_id
                if (conversationId) {
                  conversationIdRef.current = conversationId
                  dispatch({ type: 'set_conversation', conversationId })
                }
                // M4-c T-c9：result 帧必然后于服务端 run 提交发出，每轮结束都向
                // 会话摘要对齐一次发言权（断连窗丢帧、专家自动归位等路径的兜底收敛）
                syncHandoffFromSummary()
                // M4 PRD F14.10：接管/归位轮 result 正文为空（通告走 handoff 帧），
                // 用 stop 收口并移除无内容的助手占位，避免 live 留下空泡
                if (
                  (evt.data.finish_reason === 'handed_off' ||
                    evt.data.finish_reason === 'handed_back') &&
                  !evt.data.content
                ) {
                  typewriterRef.current?.finish()
                  dispatch({ type: 'stop', id: assistantId })
                  break
                }
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
          // M4-c T-c9：被动断连（网络闪断）同样向摘要对齐发言权
          syncHandoffFromSummary()
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
          syncHandoffFromSummary()
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
    [
      agentId,
      applyHandoffFrame,
      flushTokens,
      queueToken,
      refreshConversations,
      syncHandoffFromSummary,
    ],
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
        // M4 PRD F14.10：send 时刻的发言权即本轮应答方，接管轮助手气泡打专家徽标
        answeredBy: snapshot.activeHandoff?.displayName,
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
      dispatch({
        type: 'start_run',
        userText: decisionText,
        userId: nextId(),
        assistantId,
        answeredBy: snapshot.activeHandoff?.displayName,
      })

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
    dispatch({
      type: 'retry_start',
      messages: kept,
      assistantId,
      answeredBy: snapshot.activeHandoff?.displayName,
    })
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
    // M4-c T-c9：断连窗内 handoff 帧可能未送达，向服务端摘要对齐发言权
    syncHandoffFromSummary()
  }, [flushTokens, flowType, syncHandoffFromSummary])

  const handback = useCallback(async () => {
    // M4 PRD F14.9：手动归位不发 run，同一 stream 端点 handback:true，仅消费 handoff 帧
    const snapshot = stateRef.current
    const cid = conversationIdRef.current
    if (!agentId || !cid || snapshot.streaming || !snapshot.activeHandoff) return

    const controller = new AbortController()
    abortRef.current = controller
    dispatch({ type: 'set_streaming', streaming: true })
    try {
      await runAgentStream(
        agentId,
        { message: '', conversation_id: cid, handback: true },
        (evt: AgentStreamEvent) => {
          if (evt.event === 'handoff') applyHandoffFrame(evt.data)
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
            error: toMessageError(err, '归位失败'),
          },
        })
      }
    } finally {
      dispatch({ type: 'set_streaming', streaming: false })
      if (abortRef.current === controller) abortRef.current = null
    }
  }, [agentId, applyHandoffFrame])

  const selectConversation = useCallback(
    async (conversationId: string) => {
      if (!agentId || conversationId === conversationIdRef.current) return
      if (stateRef.current.streaming) return
      setConversationsLoading(true)
      try {
        const summary = conversations.find((item) => item.conversation_id === conversationId)
        const activeHandoff: ActiveHandoff | null =
          summary?.active_application_id != null
            ? {
                applicationId: summary.active_application_id,
                displayName: summary.active_application ?? '',
              }
            : null
        const rows = await listConversationMessages(agentId, conversationId)
        conversationIdRef.current = conversationId
        threadIdRef.current = null
        dispatch({
          type: 'set_messages',
          messages: historyToMessages(rows, agentId, activeHandoff),
          conversationId,
          activeHandoff,
        })
      } catch (err) {
        console.error('加载历史消息失败', err)
      } finally {
        setConversationsLoading(false)
      }
    },
    [agentId, conversations],
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
        // M4 PRD F14.10：接管中会话在侧栏透出应答专家名
        handoffAgent: item.active_application || undefined,
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
    handback,
    selectConversation,
    newConversation,
    refreshConversations,
  }
}
