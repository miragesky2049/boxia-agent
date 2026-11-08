import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatHeader } from './components/ChatHeader'
import { ChatSidebar } from './components/ChatSidebar'
import { MemoryDrawer } from './components/MemoryDrawer'
import { Composer } from './components/Composer'
import { MessageList } from './components/MessageList'
import { WelcomeHero } from './components/WelcomeHero'
import type { Suggestion } from './components/WelcomeHero'
import { useMediaQuery } from './hooks/useMediaQuery'
import type { AgentStatus, ApprovalSpec, ChatAgent, ChatMessage, ConversationItem } from './types'
import './chat.css'

// 0074 PRD F9：与后端 ConversationRunRequest.images max_length 对齐
const MAX_IMAGES = 8

export interface ChatWorkbenchProps {
  agent: ChatAgent
  conversations: ConversationItem[]
  conversationsLoading?: boolean
  activeConversationId?: string | null
  messages: ChatMessage[]
  suggestions: readonly Suggestion[]
  // 0074 F3.4：智能体开场白（无则用默认引导文案）
  openingRemarks?: string
  streaming?: boolean
  status?: AgentStatus
  userName?: string
  tenantCode?: string
  /** 0074 PRD F9：应用开启视觉时展示图片链接入口 */
  imagesEnabled?: boolean
  /** M4 PRD F16.6：智能体应用展示"我的记忆"入口 */
  memoriesEnabled?: boolean
  onSend?: (text: string, images?: string[]) => void
  onStop?: () => void
  onNewChat?: () => void
  onSelectConversation?: (id: string) => void
  onRetry?: () => void
  onAnswer?: (answer: string) => void
  /** 0074 PRD F10：审批卡裁决 */
  onApprovalDecision?: (approved: boolean, comment: string, approval: ApprovalSpec) => void
  /** M4 PRD F14.9：接管中 Composer 展示"返回主助手" */
  handbackVisible?: boolean
  onHandback?: () => void
}

export function ChatWorkbench({
  agent,
  conversations,
  conversationsLoading,
  activeConversationId,
  messages,
  suggestions,
  openingRemarks,
  streaming,
  status = 'online',
  userName,
  tenantCode,
  imagesEnabled,
  memoriesEnabled,
  onSend,
  onStop,
  onNewChat,
  onSelectConversation,
  onRetry,
  onAnswer,
  onApprovalDecision,
  handbackVisible,
  onHandback,
}: ChatWorkbenchProps) {
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [memoriesOpen, setMemoriesOpen] = useState(false)
  const [input, setInput] = useState('')
  // 0074 PRD F9：随消息发送的图片 URL（粘贴式，不落文件上传）
  const [images, setImages] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const isMobile = useMediaQuery('(max-width: 767px)')
  const hasMessages = messages.length > 0

  useEffect(() => {
    if (!isMobile) setMobileOpen(false)
  }, [isMobile])

  const send = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || streaming) return
    onSend?.(trimmed, images.length ? images : undefined)
    setInput('')
    setImages([])
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
          setImages([])
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
          onOpenMemories={memoriesEnabled ? () => setMemoriesOpen(true) : undefined}
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
              onApprove={onApprovalDecision}
            />
          ) : (
            <WelcomeHero
              agent={agent}
              suggestions={suggestions}
              openingRemarks={openingRemarks}
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
          images={images}
          imagesEnabled={imagesEnabled}
          maxImages={MAX_IMAGES}
          onAddImage={(url) => setImages((prev) => (prev.length >= MAX_IMAGES ? prev : [...prev, url]))}
          onRemoveImage={(index) => setImages((prev) => prev.filter((_, i) => i !== index))}
          handbackVisible={handbackVisible}
          onHandback={onHandback}
        />
      </main>

      {memoriesEnabled && (
        <MemoryDrawer
          open={memoriesOpen}
          applicationId={agent.id}
          onClose={() => setMemoriesOpen(false)}
        />
      )}
    </div>
  )
}
