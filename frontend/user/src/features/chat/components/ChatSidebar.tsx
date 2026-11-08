import {
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import type { ConversationItem } from '../types'

interface ChatSidebarProps {
  conversations: ConversationItem[]
  loading?: boolean
  activeId?: string | null
  collapsed: boolean
  mobileOpen?: boolean
  userName?: string
  tenantCode?: string
  onToggleCollapse: () => void
  onNewChat?: () => void
  onSelect: (id: string) => void
}

export function ChatSidebar({
  conversations,
  loading,
  activeId,
  collapsed,
  mobileOpen,
  userName = '当前用户',
  tenantCode,
  onToggleCollapse,
  onNewChat,
  onSelect,
}: ChatSidebarProps) {
  return (
    <aside
      className={`lc-sidebar${collapsed ? ' is-collapsed' : ''}${mobileOpen ? ' is-mobile-open' : ''}`}
    >
      <div className="lc-sidebar__top">
        <div className="lc-brand">
          <span className="lc-brand__mark">B</span>
          {!collapsed && <span className="lc-brand__name">Boxia Agent</span>}
        </div>
        <button
          type="button"
          className="lc-icon-btn"
          onClick={onToggleCollapse}
          aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
      </div>

      <button type="button" className="lc-new-chat" onClick={onNewChat}>
        <PlusOutlined />
        {!collapsed && <span>新会话</span>}
      </button>

      {!collapsed && (
        <div className="lc-sidebar__section-title">最近会话</div>
      )}

      <nav className="lc-conversation-list" aria-label="会话列表">
        {conversations.map((item) => (
          <button
            type="button"
            key={item.id}
            className={`lc-conversation${item.id === activeId ? ' is-active' : ''}`}
            onClick={() => onSelect(item.id)}
            title={collapsed ? item.title : undefined}
          >
            <span className="lc-conversation__dot" aria-hidden />
            {!collapsed && (
              <span className="lc-conversation__body">
                <span className="lc-conversation__title">
                  {item.title}
                  {/* M4 PRD F14.10：接管中会话标记应答专家 */}
                  {item.handoffAgent && (
                    <span className="lc-conversation__handoff" title={`由「${item.handoffAgent}」应答中`}>
                      接管中
                    </span>
                  )}
                </span>
                <span className="lc-conversation__time">{item.updatedAt}</span>
              </span>
            )}
          </button>
        ))}
        {conversations.length === 0 && !collapsed && (
          <div className="lc-sidebar__empty">
            {loading ? '正在加载会话…' : '还没有会话，开始第一次对话吧'}
          </div>
        )}
      </nav>

      <div className="lc-sidebar__footer">
        <span className="lc-user-avatar" aria-hidden>
          {userName.slice(0, 1)}
        </span>
        {!collapsed && (
          <span className="lc-user-meta">
            <span className="lc-user-meta__name">{userName}</span>
            {tenantCode && <span className="lc-user-meta__tenant">{tenantCode}</span>}
          </span>
        )}
      </div>
    </aside>
  )
}
