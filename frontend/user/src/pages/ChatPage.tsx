import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClearOutlined,
  HistoryOutlined,
  LoadingOutlined,
  MessageOutlined,
  PlusOutlined,
  SendOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { Alert, Button, Collapse, Spin, Tag, Tooltip } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgent } from '../api/agents'
import { runAgentStream, runChatflowStream } from '../api/agentRun'
import type {
  AgentStreamEvent,
  ChatflowStreamEvent,
  ChatHistoryItem,
  ToolCallTrace,
} from '../api/agentRun'
import {
  listConversationMessages,
  listConversations,
} from '../api/conversations'
import type { ConversationSummary } from '../api/conversations'
import type { UserAgentDetail } from '../api/types'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  toolTraces?: ToolCallTrace[]
  loading?: boolean
  error?: string
  /** 问答节点中断时可选回答项 */
  options?: string[]
  kind?: 'question' | 'notice'
}

const SUGGESTED_PROMPTS = [
  '你好，请介绍一下你能帮我做什么',
  '帮我快速梳理当前任务的关键点',
  '演示一次你的核心能力',
]

let messageSeq = 0
function nextMessageId(): string {
  messageSeq += 1
  return `msg_${Date.now()}_${messageSeq}`
}

function AgentAvatar({ agent, size = 40 }: { agent: UserAgentDetail; size?: number }) {
  const style: React.CSSProperties = {
    width: size,
    height: size,
    borderRadius: size * 0.28,
    objectFit: 'cover',
    flex: 'none',
  }
  if (agent.avatar_url) {
    return <img src={agent.avatar_url} alt="" style={style} />
  }
  return (
    <span
      className="chat-avatar-fallback"
      style={{
        ...style,
        display: 'grid',
        placeItems: 'center',
        color: '#fff',
        fontWeight: 700,
        fontSize: size * 0.4,
        background: 'linear-gradient(135deg, #2f6bff 0%, #7c3aed 100%)',
      }}
    >
      {agent.name.slice(0, 1).toUpperCase()}
    </span>
  )
}

export default function ChatPage() {
  const { agentId } = useParams<{ agentId: string }>()
  const [agent, setAgent] = useState<UserAgentDetail | null>(null)
  const [agentLoading, setAgentLoading] = useState(true)
  const [agentError, setAgentError] = useState<string | null>(null)

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [conversationId, setConversationId] = useState('')
  // 对话流：服务端返回的 thread，用于多轮与问答续跑
  const [chatThreadId, setChatThreadId] = useState('')
  const [pendingQuestion, setPendingQuestion] = useState<{
    question: string
    options: string[]
    threadId: string
    runId: string
  } | null>(null)

  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [conversationsLoading, setConversationsLoading] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const refreshConversations = async (cid?: string) => {
    if (!agentId) return
    setConversationsLoading(true)
    try {
      const list = await listConversations(agentId, { limit: 50 })
      setConversations(list)
      if (cid && list.length > 0) {
        setConversationId(cid)
      }
    } catch (err) {
      console.error('加载会话列表失败', err)
    } finally {
      setConversationsLoading(false)
    }
  }

  const handleSelectConversation = async (cid: string) => {
    if (!agentId || cid === conversationId) {
      setSidebarOpen(false)
      return
    }
    try {
      setConversationsLoading(true)
      const history = await listConversationMessages(agentId, cid)
      const restored: Message[] = history
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          id: m.message_id,
          role: m.role as 'user' | 'assistant',
          content: m.content,
        }))
      setMessages(restored)
      setConversationId(cid)
      setChatThreadId('')
      setPendingQuestion(null)
      setSidebarOpen(false)
    } catch (err) {
      console.error('加载历史消息失败', err)
    } finally {
      setConversationsLoading(false)
    }
  }

  const handleNewConversation = () => {
    setMessages([])
    setConversationId('')
    setChatThreadId('')
    setPendingQuestion(null)
    setInput('')
    setSidebarOpen(false)
  }

  useEffect(() => {
    if (!agentId) {
      setAgentError('智能体地址不正确')
      setAgentLoading(false)
      return
    }
    let active = true
    setAgentLoading(true)
    setAgentError(null)
    getAgent(agentId)
      .then((data) => {
        if (active) setAgent(data)
      })
      .catch((err: unknown) => {
        if (active) setAgentError(err instanceof Error ? err.message : '加载智能体失败')
      })
      .finally(() => {
        if (active) setAgentLoading(false)
      })
    return () => {
      active = false
    }
  }, [agentId])

  useEffect(() => {
    if (!agentId) return
    void refreshConversations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId])

  useEffect(() => {
    const el = scrollRef.current
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [messages])

  const historyForRequest = useMemo<ChatHistoryItem[]>(() => {
    return messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .filter((m) => !m.loading && !m.error && m.content)
      .slice(-20)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  }, [messages])

  const appendMessage = (msg: Omit<Message, 'id'>) => {
    setMessages((prev) => [...prev, { id: nextMessageId(), ...msg }])
  }

  const extractOutputText = (outputs: unknown): string => {
    if (!outputs) return ''
    if (typeof outputs === 'string') return outputs
    if (typeof outputs === 'object') {
      const values = outputs as Record<string, unknown>
      const candidate = values.output ?? values.content
      if (typeof candidate === 'string') return candidate
    }
    return ''
  }

  // 对话流：普通轮次发 message，问答中断后用 resume 续跑
  const handleChatflowSend = async (raw?: string) => {
    const text = (raw ?? input).trim()
    if (!text || sending || !agentId) return
    const answering = pendingQuestion !== null
    appendMessage({ role: 'user', content: text })
    setInput('')
    setSending(true)
    if (answering) setPendingQuestion(null)

    let emitted = 0
    let knownConversationId = conversationId

    try {
      await runChatflowStream(
        agentId,
        {
          message: answering ? '' : text,
          conversation_id: conversationId || undefined,
          thread_id: chatThreadId || undefined,
          resume: answering ? { answer: text } : undefined,
        },
        (evt: ChatflowStreamEvent) => {
          switch (evt.event) {
            case 'run_start':
              if (evt.data.conversation_id) {
                knownConversationId = evt.data.conversation_id
                if (!conversationId) {
                  setConversationId(evt.data.conversation_id)
                  void refreshConversations(evt.data.conversation_id)
                }
              }
              if (evt.data.thread_id) setChatThreadId(evt.data.thread_id)
              break
            case 'output_message': {
              const content = String(evt.data.content || '')
              if (content) {
                emitted += 1
                appendMessage({ role: 'assistant', content })
              }
              break
            }
            case 'question': {
              const question = String(evt.data.question || '请回答以下问题')
              const options = Array.isArray(evt.data.options)
                ? evt.data.options.map((item) => String(item))
                : []
              setPendingQuestion({
                question,
                options,
                threadId: String(evt.data.thread_id || ''),
                runId: String(evt.data.run_id || ''),
              })
              appendMessage({ role: 'assistant', content: question, kind: 'question', options })
              break
            }
            case 'result': {
              // 未配置输出节点时，用结束节点的返回文本兜底
              if (emitted === 0) {
                const content = extractOutputText(evt.data.outputs)
                if (content) appendMessage({ role: 'assistant', content })
              }
              if (!knownConversationId) void refreshConversations()
              break
            }
            case 'interrupted':
              appendMessage({
                role: 'assistant',
                content: '流程等待人工审批，请联系管理员处理后再继续。',
                kind: 'notice',
              })
              break
            case 'error':
              appendMessage({
                role: 'assistant',
                content: evt.data.message || '对话流运行失败',
                error: evt.data.message || '对话流运行失败',
              })
              break
            default:
              // node_start / node_end / final 不直接渲染
              break
          }
        },
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : '调用对话流失败'
      appendMessage({ role: 'assistant', content: msg, error: msg })
    } finally {
      setSending(false)
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }

  const handleSend = async (raw?: string) => {
    // 对话流使用多轮 SSE + 问答中断协议，和工作流/普通智能体不同
    if (agent?.flow_type === 'chatflow') {
      await handleChatflowSend(raw)
      return
    }

    const text = (raw ?? input).trim()
    if (!text || sending || !agentId) return

    const userMsg: Message = { id: nextMessageId(), role: 'user', content: text }
    const assistantMsg: Message = {
      id: nextMessageId(),
      role: 'assistant',
      content: '',
      loading: true,
    }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput('')
    setSending(true)

    // 本地累积的工具轨迹：SSE 多次 tool_end 时合并
    const toolTraces: ToolCallTrace[] = []

    const patchAssistant = (patch: Partial<Message>) => {
      setMessages((prev) =>
        prev.map((m) => (m.id === assistantMsg.id ? { ...m, ...patch } : m)),
      )
    }

    try {
      await runAgentStream(
        agentId,
        {
          query: text,
          conversation_id: conversationId || undefined,
          history: historyForRequest,
        },
        (evt: AgentStreamEvent) => {
          switch (evt.event) {
            case 'llm_token':
              // 流式增量：逐 token 追加到 assistant 气泡，实现打字机效果
              if (evt.data.delta) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsg.id
                      ? { ...m, loading: false, content: m.content + evt.data.delta }
                      : m,
                  ),
                )
              }
              break
            case 'llm_end':
              // 每轮 LLM 返回的 content 是该轮完整输出；多轮时以最后一轮为准
              // 流式场景下 content 已通过 llm_token 累积，这里仅在非流式回退时覆盖
              if (evt.data.content && !evt.data.usage_streamed) {
                patchAssistant({ loading: false, content: evt.data.content })
              } else {
                patchAssistant({ loading: false })
              }
              break
            case 'tool_start':
              // 工具开始执行：临时占位，等 tool_end 填充
              toolTraces.push({
                tool_call_id: evt.data.tool_call_id,
                tool_name: evt.data.name,
                arguments: evt.data.arguments,
                observation: '',
                is_error: false,
              })
              patchAssistant({ toolTraces: [...toolTraces] })
              break
            case 'tool_end': {
              const idx = toolTraces.findIndex(
                (t) => t.tool_call_id === evt.data.tool_call_id,
              )
              if (idx >= 0) {
                toolTraces[idx] = {
                  ...toolTraces[idx],
                  observation: evt.data.observation,
                  is_error: evt.data.is_error,
                }
              } else {
                toolTraces.push({
                  tool_call_id: evt.data.tool_call_id,
                  tool_name: evt.data.name,
                  arguments: {},
                  observation: evt.data.observation,
                  is_error: evt.data.is_error,
                })
              }
              patchAssistant({ toolTraces: [...toolTraces] })
              break
            }
            case 'result':
              if (!conversationId) {
                setConversationId(evt.data.conversation_id)
                void refreshConversations(evt.data.conversation_id)
              } else {
                void refreshConversations()
              }
              patchAssistant({
                loading: false,
                content: evt.data.content,
                toolTraces: evt.data.tool_traces,
              })
              break
            case 'error':
              patchAssistant({ loading: false, error: evt.data.message })
              break
            default:
              // run_start / llm_start / final 不影响 UI
              break
          }
        },
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : '调用智能体失败'
      patchAssistant({ loading: false, error: msg })
    } finally {
      setSending(false)
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void handleSend()
    }
  }

  const renderToolTraces = (traces: ToolCallTrace[]) => {
    if (!traces || traces.length === 0) return null
    return (
      <Collapse
        size="small"
        ghost
        style={{ marginTop: 8, background: 'rgba(245, 247, 250, 0.6)', borderRadius: 8 }}
        items={[
          {
            key: 'traces',
            label: (
              <span style={{ fontSize: 12, color: '#86909c' }}>
                <ToolOutlined style={{ marginRight: 6 }} />
                调用了 {traces.length} 个工具
              </span>
            ),
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {traces.map((t, idx) => (
                  <div
                    key={t.tool_call_id || idx}
                    style={{
                      padding: '8px 10px',
                      borderRadius: 6,
                      background: '#fff',
                      border: '1px solid #eef0f4',
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Tag color={t.is_error ? 'red' : 'blue'} style={{ margin: 0 }}>
                        {t.tool_name}
                      </Tag>
                      <span style={{ color: '#86909c', fontSize: 11 }}>
                        {t.is_error ? '失败' : '成功'}
                      </span>
                    </div>
                    <pre
                      style={{
                        margin: '6px 0 0',
                        padding: 6,
                        background: '#f7f8fc',
                        borderRadius: 4,
                        fontSize: 11,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        fontFamily: 'ui-monospace, Consolas, monospace',
                        maxHeight: 140,
                        overflow: 'auto',
                      }}
                    >
                      {t.observation}
                    </pre>
                  </div>
                ))}
              </div>
            ),
          },
        ]}
      />
    )
  }

  return (
    <div className="chat-page">
      <aside className={`chat-sidebar ${sidebarOpen ? 'chat-sidebar--open' : ''}`}>
        <div className="chat-sidebar__header">
          <span className="chat-sidebar__title">
            <HistoryOutlined /> 历史会话
          </span>
          <Button
            type="text"
            size="small"
            icon={<PlusOutlined />}
            onClick={handleNewConversation}
            disabled={sending}
          >
            新会话
          </Button>
        </div>
        <div className="chat-sidebar__list">
          {conversationsLoading && conversations.length === 0 ? (
            <div className="chat-sidebar__empty">
              <Spin size="small" />
            </div>
          ) : conversations.length === 0 ? (
            <div className="chat-sidebar__empty">
              <MessageOutlined />
              <span>暂无历史会话</span>
            </div>
          ) : (
            conversations.map((c) => (
              <button
                key={c.conversation_id}
                type="button"
                className={`chat-sidebar__item ${
                  c.conversation_id === conversationId ? 'chat-sidebar__item--active' : ''
                }`}
                onClick={() => void handleSelectConversation(c.conversation_id)}
                disabled={sending}
              >
                <div className="chat-sidebar__item-title">
                  {c.title || '未命名会话'}
                </div>
                {c.updated_at && (
                  <div className="chat-sidebar__item-time">
                    {new Date(c.updated_at).toLocaleString()}
                  </div>
                )}
              </button>
            ))
          )}
        </div>
      </aside>
      {sidebarOpen && (
        <div
          className="chat-sidebar__mask"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <header className="chat-header">
        <Link to="/" className="chat-header__back">
          <ArrowLeftOutlined />
          <span>返回</span>
        </Link>
        <Button
          type="text"
          icon={<HistoryOutlined />}
          onClick={() => setSidebarOpen((v) => !v)}
        >
          会话
        </Button>
        {agent && (
          <div className="chat-header__agent">
            <AgentAvatar agent={agent} size={36} />
            <div className="chat-header__agent-meta">
              <div className="chat-header__agent-name">{agent.name}</div>
              <div className="chat-header__agent-status">
                <span className="chat-header__dot" />
                在线 · 随时为你服务
              </div>
            </div>
          </div>
        )}
        <div className="chat-header__actions">
          <Tooltip title="开启新会话">
            <Button
              type="text"
              icon={<ClearOutlined />}
              onClick={handleNewConversation}
              disabled={messages.length === 0 || sending}
            >
              新会话
            </Button>
          </Tooltip>
        </div>
      </header>

      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-container">
          {agentLoading ? (
            <div className="chat-empty">
              <Spin size="large" tip="正在加载智能体..." />
            </div>
          ) : agentError || !agent ? (
            <div className="chat-empty">
              <Alert type="error" showIcon message={agentError ?? '智能体不存在或未授权'} />
              <Link to="/">
                <Button style={{ marginTop: 16 }}>返回列表</Button>
              </Link>
            </div>
          ) : messages.length === 0 ? (
            <div className="chat-welcome">
              <div className="chat-welcome__avatar-wrap">
                <AgentAvatar agent={agent} size={72} />
                <span className="chat-welcome__badge">
                  <CheckCircleOutlined />
                </span>
              </div>
              <h1 className="chat-welcome__title">{agent.name}</h1>
              <p className="chat-welcome__desc">
                {agent.description.trim() || '通过自然语言对话，让智能体为你完成任务。'}
              </p>
              <div className="chat-welcome__suggests">
                {SUGGESTED_PROMPTS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="chat-suggest-chip"
                    onClick={() => void handleSend(s)}
                    disabled={sending}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-messages">
              {messages.map((m) => {
                if (m.role === 'user') {
                  return (
                    <div key={m.id} className="chat-row chat-row--user">
                      <div className="chat-bubble chat-bubble--user">{m.content}</div>
                    </div>
                  )
                }
                return (
                  <div key={m.id} className="chat-row chat-row--assistant">
                    {agent && <AgentAvatar agent={agent} size={32} />}
                    <div className="chat-bubble chat-bubble--assistant">
                      {m.loading ? (
                        <div className="chat-typing">
                          <span />
                          <span />
                          <span />
                        </div>
                      ) : m.error ? (
                        <Alert type="error" showIcon message={m.error} />
                      ) : (
                        <>
                          <div className="chat-bubble__content chat-markdown">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {m.content}
                            </ReactMarkdown>
                          </div>
                          {m.options && m.options.length > 0 && (
                            <div
                              style={{
                                display: 'flex',
                                flexWrap: 'wrap',
                                gap: 8,
                                marginTop: 10,
                              }}
                            >
                              {m.options.map((opt) => (
                                <button
                                  key={opt}
                                  type="button"
                                  className="chat-suggest-chip"
                                  onClick={() => void handleSend(opt)}
                                  // 只允许回答当前待回复的问题
                                  disabled={
                                    sending ||
                                    pendingQuestion === null ||
                                    pendingQuestion.question !== m.content
                                  }
                                >
                                  {opt}
                                </button>
                              ))}
                            </div>
                          )}
                          {m.toolTraces && m.toolTraces.length > 0 && renderToolTraces(m.toolTraces)}
                        </>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <textarea
            ref={textareaRef}
            className="chat-input"
            placeholder="输入你的问题，Enter 发送，Shift+Enter 换行"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={!agent || agentLoading || sending}
            rows={1}
            autoFocus
          />
          <button
            type="button"
            className="chat-send-btn"
            onClick={() => void handleSend()}
            disabled={!input.trim() || sending || !agent}
            aria-label="发送"
          >
            {sending ? <LoadingOutlined /> : <SendOutlined />}
          </button>
        </div>
        <div className="chat-input-tip">
          由 <span>{agent?.name ?? 'AI'}</span> 驱动 · 内容由智能体生成，请谨慎甄别
        </div>
      </div>
    </div>
  )
}
