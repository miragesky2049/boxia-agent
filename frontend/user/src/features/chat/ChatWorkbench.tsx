import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatHeader } from './components/ChatHeader'
import { ChatSidebar } from './components/ChatSidebar'
import { Composer } from './components/Composer'
import { MessageList } from './components/MessageList'
import { WelcomeHero } from './components/WelcomeHero'
import type { Suggestion } from './components/WelcomeHero'
import { useMediaQuery } from './hooks/useMediaQuery'
import type { AgentStatus, ChatAgent, ChatMessage, ConversationItem } from './types'
import './chat.css'

export interface ChatWorkbenchProps {
  agent: ChatAgent
  conversations: ConversationItem[]
  conversationsLoading?: boolean
  activeConversationId?: string | null
  messages: ChatMessage[]
  suggestions: readonly Suggestion[]
  streaming?: boolean
  status?: AgentStatus
  userName?: string
  tenantCode?: string
  onSend?: (text: string) => void
  onStop?: () => void
  onNewChat?: () => void
  onSelectConversation?: (id: string) => void
  onRetry?: () => void
  onAnswer?: (answer: string) => void
}

export function ChatWorkbench({
  agent,
  conversations,
  conversationsLoading,
  activeConversationId,
  messages,
  suggestions,
  streaming,
  status = 'online',
  userName,
  tenantCode,
  onSend,
  onStop,
  onNewChat,
  onSelectConversation,
  onRetry,
  onAnswer,
}: ChatWorkbenchProps) {
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const isMobile = useMediaQuery('(max-width: 767px)')
  const hasMessages = messages.length > 0

  useEffect(() => {
    if (!isMobile) setMobileOpen(false)
  }, [isMobile])

  const send = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || streaming) return
    onSend?.(trimmed)
    setInput('')
  }

  return (
    <div className={`lc-page${hasMessages ? ' is-chat' : ' is-welcome'}`}>
      <ChatSidebar
        conversations={conversations}
        loading={conversationsLoading}
        activeId={activeConversationId}
        collapsed={collapsed && !isMobile}
        mobileOpen={mobileOpen}
        userName={userName}
        tenantCode={tenantCode}
        onToggleCollapse={() => setCollapsed((prev) => !prev)}
        onNewChat={() => {
          setInput('')
          setMobileOpen(false)
          onNewChat?.()
        }}
        onSelect={(id) => {
          setMobileOpen(false)
          onSelectConversation?.(id)
        }}
      />

      {mobileOpen && (
        <button
          type="button"
          className="lc-backdrop"
          aria-label="关闭会话列表"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <main className="lc-main">
        <ChatHeader
          agent={agent}
          status={streaming ? 'thinking' : status}
          onBack={() => navigate('/agents')}
          onOpenMenu={() => setMobileOpen(true)}
        />

        <div className="lc-scroll" ref={scrollRef}>
          {hasMessages ? (
            <MessageList
              messages={messages}
              agent={agent}
              streaming={streaming}
              scrollRef={scrollRef}
              onRetry={onRetry}
              onAnswer={onAnswer}
            />
          ) : (
            <WelcomeHero
              agent={agent}
              suggestions={suggestions}
              onPick={(title) => send(title)}
            />
          )}
        </div>

        <Composer
          value={input}
          streaming={streaming}
          onChange={setInput}
          onSend={() => send(input)}
          onStop={onStop}
        />
      </main>
    </div>
  )
}
