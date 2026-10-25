import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { getTenantCode, getTenantParam, isLocalHost, setTenantCode } from '../tenant/scope'

/** 只允许站内相对路径，避免 next 参数造成开放重定向。 */
function sanitizeNext(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/'
  return value
}

export default function LoginPage() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [tenantCode, setTenant] = useState(() => getTenantCode())
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const nextPath = sanitizeNext(searchParams.get('next'))
  const localHost = isLocalHost()

  useEffect(() => {
    const param = getTenantParam()
    if (param) {
      setTenantCode(param)
      setTenant(param)
    }
  }, [])

  if (user) {
    return <Navigate to={nextPath} replace />
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting) return
    setError(null)
    if (!username.trim() || !password) {
      setError('请输入账号和密码')
      return
    }
    if (localHost) {
      setTenantCode(tenantCode)
    }
    setSubmitting(true)
    try {
      await signIn(username.trim(), password)
      navigate(nextPath, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败，请稍后再试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login">
      <section className="login__card">
        <span className="badge">用户端</span>
        <h1>登录 Boxia Agent</h1>
        <p className="login__desc">使用租户分配给你的账号登录，查看已授权的智能体。</p>
        <form className="login__form" onSubmit={handleSubmit}>
          <label className="field">
            <span>账号</span>
            <input
              value={username}
              autoComplete="username"
              autoFocus
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label className="field">
            <span>密码</span>
            <input
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {localHost && (
            <label className="field">
              <span>租户编码（本地调试）</span>
              <input
                value={tenantCode}
                placeholder="例如 acme"
                autoComplete="off"
                onChange={(event) => setTenant(event.target.value)}
              />
              <small>线上由租户子域名决定，本地回环地址通过请求头模拟。</small>
            </label>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="button button--primary" disabled={submitting}>
            {submitting ? '登录中…' : '登录'}
          </button>
        </form>
      </section>
    </main>
  )
}
