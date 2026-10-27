import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClearOutlined,
  LoadingOutlined,
  SendOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { Alert, Button, Collapse, Spin, Tag, Tooltip } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgent } from '../api/agents'
import { runAgent } from '../api/agentRun'
import type { ChatHistoryItem, ToolCallTrace } from '../api/agentRun'
import type { UserAgentDetail } from '../api/types'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  toolTraces?: ToolCallTrace[]
  loading?: boolean
  error?: string
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

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

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

  const handleSend = async (raw?: string) => {
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

    try {
      const result = await runAgent(agentId, {
        query: text,
        conversation_id: conversationId || undefined,
        history: historyForRequest,
      })
      if (!conversationId) setConversationId(result.conversation_id)
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id
            ? {
                ...m,
                content: result.content,
                toolTraces: result.tool_traces,
                loading: false,
              }
            : m,
        ),
      )
    } catch (err) {
      const msg = err instanceof Error ? err.message : '调用智能体失败'
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id ? { ...m, loading: false, error: msg } : m,
        ),
      )
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

  const handleReset = () => {
    setMessages([])
    setConversationId('')
    setInput('')
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
      <header className="chat-header">
        <Link to="/" className="chat-header__back">
          <ArrowLeftOutlined />
          <span>返回</span>
        </Link>
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
              onClick={handleReset}
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
