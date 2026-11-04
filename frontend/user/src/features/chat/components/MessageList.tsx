import { ArrowDownOutlined } from '@ant-design/icons'
import { useEffect, useRef, useState, type RefObject } from 'react'
import type { ChatAgent, ChatMessage } from '../types'
import { MessageBubble } from './MessageBubble'

interface MessageListProps {
  messages: ChatMessage[]
  agent: ChatAgent
  streaming?: boolean
  scrollRef?: RefObject<HTMLDivElement>
  onRetry?: () => void
  onAnswer?: (answer: string) => void
}

const STICKY_THRESHOLD = 160
const JUMP_THRESHOLD = 240

export function MessageList({
  messages,
  agent,
  streaming,
  scrollRef,
  onRetry,
  onAnswer,
}: MessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const prevCountRef = useRef(0)
  const [showJump, setShowJump] = useState(false)
  const waiting = Boolean(streaming) && messages[messages.length - 1]?.role === 'user'

  useEffect(() => {
    const container = scrollRef?.current
    if (!container) return
    const handleScroll = () => {
      const distance = container.scrollHeight - container.scrollTop - container.clientHeight
      setShowJump(distance > JUMP_THRESHOLD)
    }
    handleScroll()
    container.addEventListener('scroll', handleScroll, { passive: true })
    return () => container.removeEventListener('scroll', handleScroll)
  }, [scrollRef])

  useEffect(() => {
    const end = endRef.current
    if (!end) return
    const grew = messages.length - prevCountRef.current
    const last = messages[messages.length - 1]
    prevCountRef.current = messages.length

    const container = scrollRef?.current
    // 用户主动发消息或切换会话时强制贴底；流式追加时只在接近底部时跟随，避免打断向上翻阅
    const force = last?.role === 'user' || grew > 1
    if (!container || force) {
      end.scrollIntoView({ block: 'end' })
      setShowJump(false)
      return
    }
    const distance = container.scrollHeight - container.scrollTop - container.clientHeight
    if (distance < STICKY_THRESHOLD) {
      end.scrollIntoView({ block: 'end' })
      setShowJump(false)
    } else if (distance > JUMP_THRESHOLD) {
      setShowJump(true)
    }
  }, [messages, waiting, scrollRef])

  return (
    <div className="lc-thread" role="log" aria-live={streaming ? 'off' : 'polite'}>
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          agent={agent}
          onRetry={onRetry}
          onAnswer={onAnswer}
        />
      ))}
      {waiting && (
        <div className="lc-msg lc-msg--assistant">
          <span className="lc-msg__avatar" aria-hidden>
            {agent.avatarText}
          </span>
          <div className="lc-msg__body">
            <div className="lc-thinking" aria-label="正在思考">
              <span />
              <span />
              <span />
            </div>
          </div>
        </div>
      )}
      {showJump && (
        <button
          type="button"
          className="lc-jump"
          onClick={() => endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })}
        >
          <ArrowDownOutlined />
          <span>回到底部</span>
        </button>
      )}
      <div ref={endRef} />
    </div>
  )
}
