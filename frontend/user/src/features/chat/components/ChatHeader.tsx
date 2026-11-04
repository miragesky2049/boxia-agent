import { ArrowLeftOutlined, MenuOutlined } from '@ant-design/icons'
import type { AgentStatus, ChatAgent } from '../types'

interface ChatHeaderProps {
  agent: ChatAgent
  status?: AgentStatus
  onBack?: () => void
  onOpenMenu?: () => void
}

export function ChatHeader({ agent, status = 'online', onBack, onOpenMenu }: ChatHeaderProps) {
  return (
    <header className="lc-header">
      {onOpenMenu && (
        <button
          type="button"
          className="lc-icon-btn lc-menu-btn"
          onClick={onOpenMenu}
          aria-label="打开会话列表"
        >
          <MenuOutlined />
        </button>
      )}
      <button type="button" className="lc-icon-btn" onClick={onBack} aria-label="返回应用列表">
        <ArrowLeftOutlined />
      </button>

      <div className="lc-header__agent">
        <span className="lc-agent-avatar" aria-hidden>
          {agent.avatarText}
        </span>
        <span className="lc-header__agent-meta">
          <span className="lc-header__agent-name">{agent.name}</span>
          <span className={`lc-status${status === 'thinking' ? ' is-thinking' : ''}`}>
            <span className="lc-status__dot" aria-hidden />
            {status === 'thinking' ? '思考中…' : '在线'}
          </span>
        </span>
      </div>
    </header>
  )
}
