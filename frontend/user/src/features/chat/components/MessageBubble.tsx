import { CheckOutlined, CopyOutlined, SwapOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { ApprovalSpec, ChatAgent, ChatMessage } from '../types'
import { ApprovalCard } from './ApprovalCard'
import { AssistantContent } from './AssistantContent'
import { ErrorNotice } from './ErrorNotice'
import { NoticeCard } from './NoticeCard'
import { PlanProgressCard } from './PlanProgressCard'
import { QuestionCard } from './QuestionCard'
import { ToolTraceCard } from './ToolTraceCard'

interface MessageBubbleProps {
  message: ChatMessage
  agent: ChatAgent
  onRetry?: () => void
  onAnswer?: (answer: string) => void
  /** 0074 PRD F10：审批卡裁决（携带该卡续跑坐标，支持多卡并存时精确恢复） */
  onApprove?: (approved: boolean, comment: string, approval: ApprovalSpec) => void
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

export function MessageBubble({ message, agent, onRetry, onAnswer, onApprove }: MessageBubbleProps) {
  // M4 PRD F14.10：发言权移交通告渲染为居中系统气泡，不带助手头像/正文区
  if (message.handoffNotice) {
    return (
      <div className="lc-handoff-notice">
        <SwapOutlined className="lc-handoff-notice__icon" />
        <span>{message.handoffNotice}</span>
      </div>
    )
  }

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
        {message.answeredBy && (
          <div className="lc-msg__badge">{`由「${message.answeredBy}」应答`}</div>
        )}
        {(message.plan?.length || message.reflects?.length) && (
          <PlanProgressCard tasks={message.plan ?? []} reflects={message.reflects ?? []} />
        )}

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

        {message.approval && (
          <ApprovalCard
            approval={message.approval}
            onDecision={(approved, comment) =>
              onApprove?.(approved, comment, message.approval as ApprovalSpec)
            }
          />
        )}

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
