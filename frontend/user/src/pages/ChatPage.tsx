import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ClearOutlined,
  LoadingOutlined,
  SendOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { Alert, App as AntdApp, Button, Collapse, Spin, Tag, Tooltip } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getAgent } from '../api/agents'
import { runAgentStream } from '../api/agentRun'
import type { AgentStreamEvent, ChatHistoryItem, ToolCallTrace } from '../api/agentRun'
import type { UserAgentDetail } from '../api/types'
import { ActionBar, UploadMaterial } from '../components/boxiaclaw-cmp'
import type { ActionBarAction, UploadedMaterialFile } from '../components/boxiaclaw-cmp'

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

/**
 * 组件渲染协议：assistant 消息中使用围栏代码块声明前端组件，
 * 语言标记为 boxiaclaw-component，内容为 JSON：
 *
 * ```boxiaclaw-component
 * {"name":"@boxiaclaw-elearning-cmp/upload-material","props":{"sceneRobotId":"xxx"}}
 * ```
 */
const COMPONENT_BLOCK_RE = /```boxiaclaw-component\s*\n([\s\S]*?)```/g

interface ContentSegment {
  type: 'markdown' | 'component'
  value: string
}

function parseContentSegments(content: string): ContentSegment[] {
  const segments: ContentSegment[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  COMPONENT_BLOCK_RE.lastIndex = 0
  while ((match = COMPONENT_BLOCK_RE.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ type: 'markdown', value: content.slice(lastIndex, match.index) })
    }
    segments.push({ type: 'component', value: match[1].trim() })
    lastIndex = COMPONENT_BLOCK_RE.lastIndex
  }
  if (lastIndex < content.length) {
    segments.push({ type: 'markdown', value: content.slice(lastIndex) })
  }
  return segments
}

interface ComponentBlockPayload {
  name: string
  props?: Record<string, unknown>
}

function isComponentBlockPayload(data: unknown): data is ComponentBlockPayload {
  return (
    typeof data === 'object' &&
    data !== null &&
    typeof (data as { name?: unknown }).name === 'string'
  )
}

function BoxiaclawComponentBlock({ json }: { json: string }) {
  const { message } = AntdApp.useApp()

  const parsed = useMemo(() => {
    try {
      return { ok: true, data: JSON.parse(json) as unknown }
    } catch (err) {
      return {
        ok: false as const,
        error: err instanceof Error ? err.message : 'JSON 解析失败',
      }
    }
  }, [json])

  if (!parsed.ok) {
    return (
      <Alert
        type="error"
        showIcon
        message="组件声明解析失败"
        description={parsed.error}
      />
    )
  }

  const data = parsed.data
  if (!isComponentBlockPayload(data)) {
    return <Alert type="warning" showIcon message="组件声明格式不正确" description={json} />
  }

  if (data.name === '@boxiaclaw-elearning-cmp/upload-material') {
    const props = data.props ?? {}
    return (
      <UploadMaterial
        sceneRobotId={typeof props.sceneRobotId === 'string' ? props.sceneRobotId : undefined}
        disabled={typeof props.disabled === 'boolean' ? props.disabled : undefined}
        onUploaded={(files: UploadedMaterialFile[]) => {
          message.success(`已上传 ${files.filter((f) => f.status === 'done').length} 份资料`)
        }}
        onSkip={() => {
          message.info('已跳过资料上传')
        }}
      />
    )
  }

  if (data.name === '@boxiaclaw-elearning-cmp/action-bar') {
    const placement =
      data.props?.placement === 'right' || data.props?.placement === 'center'
        ? data.props.placement
        : 'left'
    const rawActions = Array.isArray(data.props?.actions) ? data.props.actions : []
    const actions: ActionBarAction[] = rawActions.map((a) => {
      const item = (a ?? {}) as Record<string, unknown>
      return {
        label: typeof item.label === 'string' ? item.label : '',
        type: item.type === 'primary' || item.type === 'text' ? item.type : 'secondary',
        action:
          typeof item.action === 'object' && item.action !== null
            ? (item.action as { type: string })
            : undefined,
      }
    })
    return (
      <ActionBar
        placement={placement}
        actions={actions}
        onAction={(action) => {
          if (action.action?.type === 'goto_free_detail') {
            message.success('剧本已保存，即将进入详情')
          }
        }}
      />
    )
  }

  return (
    <Alert
      type="warning"
      showIcon
      message={`未识别的组件：${data.name}`}
      description={json}
    />
  )
}

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
            case 'llm_end':
              // 每轮 LLM 返回的 content 是该轮完整输出；多轮时以最后一轮为准
              if (evt.data.content) {
                patchAssistant({ loading: false, content: evt.data.content })
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
              if (!conversationId) setConversationId(evt.data.conversation_id)
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
                            {parseContentSegments(m.content).map((seg, idx) => {
                              if (seg.type === 'component') {
                                return <BoxiaclawComponentBlock key={idx} json={seg.value} />
                              }
                              return (
                                <ReactMarkdown key={idx} remarkPlugins={[remarkGfm]}>
                                  {seg.value}
                                </ReactMarkdown>
                              )
                            })}
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
