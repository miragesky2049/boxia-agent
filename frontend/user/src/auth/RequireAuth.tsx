import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()

  // 仅 dev 构建生效：?wfMock= 静态版工作台不访问真实接口，供 UI 验收截图免登录
  if (import.meta.env.DEV && location.search.includes('wfMock=')) {
    return <>{children}</>
  }

  if (loading) {
    return (
      <main className="page-state">
        <p className="state-text">正在恢复登录状态…</p>
      </main>
    )
  }

  if (!user) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`)
    return <Navigate to={`/login?next=${next}`} replace />
  }

  return <>{children}</>
}
