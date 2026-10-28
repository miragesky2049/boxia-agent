import { LogoutOutlined, UserOutlined } from '@ant-design/icons'
import { Avatar, Dropdown, Tag } from 'antd'
import type { MenuProps } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function AppHeader() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  const handleSignOut = async () => {
    await signOut()
    navigate('/login', { replace: true })
  }

  const items: MenuProps['items'] = user
    ? [
        {
          key: 'user',
          disabled: true,
          label: (
            <div style={{ padding: '4px 0' }}>
              <div style={{ fontWeight: 600, color: '#1d2129' }}>
                {user.display_name || user.username}
              </div>
              <div style={{ marginTop: 4 }}>
                <Tag color="blue">{user.role_name || '未分配角色'}</Tag>
              </div>
            </div>
          ),
        },
        { type: 'divider' },
        {
          key: 'logout',
          icon: <LogoutOutlined />,
          label: '退出登录',
          danger: true,
          onClick: () => {
            void handleSignOut()
          },
        },
      ]
    : []

  const displayName = user?.display_name || user?.username || ''
  const avatarChar = displayName.slice(0, 1).toUpperCase() || <UserOutlined />

  return (
    <header className="app-header">
      <div className="app-header__brand">
        <span className="app-header__logo">B</span>
        <div>
          <div className="app-header__title">Boxia Agent</div>
          <div className="app-header__subtitle">智能体用户门户</div>
        </div>
      </div>
      {user && (
        <Dropdown menu={{ items }} placement="bottomRight" trigger={['click']}>
          <Avatar
            style={{
              cursor: 'pointer',
              background: 'linear-gradient(135deg, #2f6bff 0%, #7c3aed 100%)',
            }}
          >
            {avatarChar}
          </Avatar>
        </Dropdown>
      )}
    </header>
  )
}
