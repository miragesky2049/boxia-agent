import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export default function AppHeader() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  const handleSignOut = async () => {
    await signOut()
    navigate('/login', { replace: true })
  }

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__logo">B</span>
        <div>
          <strong>Boxia Agent</strong>
          <small>智能体用户门户</small>
        </div>
      </div>
      {user && (
        <div className="topbar__user">
          <span className="topbar__name">{user.display_name || user.username}</span>
          <span className="tag">{user.role_name}</span>
          <button type="button" className="button button--ghost" onClick={handleSignOut}>
            退出登录
          </button>
        </div>
      )}
    </header>
  )
}
