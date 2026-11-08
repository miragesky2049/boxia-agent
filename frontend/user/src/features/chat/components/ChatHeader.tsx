import { ArrowLeftOutlined, MenuOutlined, BookOutlined } from '@ant-design/icons'
import type { AgentStatus, ChatAgent } from '../types'

interface ChatHeaderProps {
  agent: ChatAgent
  status?: AgentStatus
  onBack?: () => void
  onOpenMenu?: () => void
  /** M4 PRD F16.6：智能体应用提供"我的记忆"入口 */
  onOpenMemories?: () => void
}

export function ChatHeader({ agent, status = 'online', onBack, onOpenMenu, onOpenMemories }: ChatHeaderProps) {
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

      {onOpenMemories && (
        <button
          type="button"
          className="lc-icon-btn lc-header__memories"
          onClick={onOpenMemories}
          aria-label="我的记忆"
          title="我的记忆"
        >
          <BookOutlined />
        </button>
      )}
    </header>
  )
}
