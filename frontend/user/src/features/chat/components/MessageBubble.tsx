import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { ChatAgent, ChatMessage } from '../types'
import { AssistantContent } from './AssistantContent'
import { ErrorNotice } from './ErrorNotice'
import { NoticeCard } from './NoticeCard'
import { QuestionCard } from './QuestionCard'
import { ToolTraceCard } from './ToolTraceCard'

interface MessageBubbleProps {
  message: ChatMessage
  agent: ChatAgent
  onRetry?: () => void
  onAnswer?: (answer: string) => void
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  return (
    <button type="button" className="lc-msg-action" onClick={handleCopy}>
      {copied ? <CheckOutlined /> : <CopyOutlined />}
      <span>{copied ? '已复制' : '复制'}</span>
    </button>
  )
}

export function MessageBubble({ message, agent, onRetry, onAnswer }: MessageBubbleProps) {
  if (message.role === 'user') {
    return (
      <div className="lc-msg lc-msg--user">
        <div className="lc-bubble-user">{message.content}</div>
      </div>
    )
  }

  const isThinking = message.streaming && !message.content

  return (
    <div className="lc-msg lc-msg--assistant">
      <span className="lc-msg__avatar" aria-hidden>
        {agent.avatarText}
      </span>
      <div className="lc-msg__body">
        {message.tools?.map((trace) => (
          <ToolTraceCard key={trace.id} trace={trace} />
        ))}

        {isThinking && (
          <div className="lc-thinking" aria-label="正在思考">
            <span />
            <span />
            <span />
          </div>
        )}

        {message.content && (
          <AssistantContent content={message.content} streaming={message.streaming} />
        )}

        {message.notice && <NoticeCard text={message.notice} tone={message.noticeTone} />}

        {message.question && <QuestionCard question={message.question} onSubmit={onAnswer} />}

        {message.error && <ErrorNotice error={message.error} onRetry={onRetry} />}

        {message.content && !message.streaming && (
          <div className="lc-msg__actions">
            <CopyButton text={message.content} />
          </div>
        )}
      </div>
    </div>
  )
}
