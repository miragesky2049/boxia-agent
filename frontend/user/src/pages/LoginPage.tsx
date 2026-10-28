import {
  LockOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  SafetyOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { App, Button, Form, Input } from 'antd'
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

interface FeatureItem {
  icon: React.ReactNode
  title: string
  desc: string
}

const FEATURES: FeatureItem[] = [
  {
    icon: <SafetyCertificateOutlined />,
    title: '角色化授权',
    desc: '按角色分发可见的智能体，精准控制访问范围',
  },
  {
    icon: <SafetyOutlined />,
    title: '租户级隔离',
    desc: '多租户身份体系，会话与数据严格隔离',
  },
  {
    icon: <RocketOutlined />,
    title: '开箱即用',
    desc: '登录即可使用已授权的智能体与内置资源',
  },
]

export default function LoginPage() {
  const { user, signIn } = useAuth()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [tenantCode, setTenant] = useState(() => getTenantCode())
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
    if (!username.trim() || !password) {
      message.warning('请输入账号和密码')
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
      message.error(err instanceof Error ? err.message : '登录失败，请稍后再试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <aside className="login-brand">
        <span className="login-brand__orb login-brand__orb--1" />
        <span className="login-brand__orb login-brand__orb--2" />
        <span className="login-brand__orb login-brand__orb--3" />

        <div className="login-brand__logo">
          <span className="login-brand__logo-mark">B</span>
          <span className="login-brand__logo-text">Boxia Agent</span>
        </div>

        <div className="login-brand__hero">
          <h1>你的智能体工作台</h1>
          <p>登录后即可查看并使用租户授权给你的智能体，安全、高效、开箱即用。</p>
        </div>

        <div className="login-brand__features">
          {FEATURES.map((feature) => (
            <div key={feature.title} className="login-brand__feature">
              <span className="login-brand__feature-icon">{feature.icon}</span>
              <div>
                <p className="login-brand__feature-title">{feature.title}</p>
                <p className="login-brand__feature-desc">{feature.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <section className="login-form-side">
        <div className="login-form-wrapper">
          <h2>欢迎回来</h2>
          <p className="login-form-subtitle">请使用你的账号登录以继续</p>

          <Form layout="vertical" onSubmitCapture={handleSubmit}>
            <Form.Item
              label="账号"
              required
              validateStatus={undefined}
              style={{ marginBottom: 18 }}
            >
              <Input
                size="large"
                prefix={<UserOutlined style={{ color: '#86909c' }} />}
                value={username}
                autoComplete="username"
                autoFocus
                placeholder="请输入账号"
                onChange={(event) => setUsername(event.target.value)}
              />
            </Form.Item>

            <Form.Item label="密码" required style={{ marginBottom: localHost ? 18 : 24 }}>
              <Input.Password
                size="large"
                prefix={<LockOutlined style={{ color: '#86909c' }} />}
                value={password}
                autoComplete="current-password"
                placeholder="请输入密码"
                onChange={(event) => setPassword(event.target.value)}
              />
            </Form.Item>

            {localHost && (
              <Form.Item
                label="租户编码（本地调试）"
                style={{ marginBottom: 24 }}
                extra="线上由租户子域名决定，本地回环地址通过请求头模拟。"
              >
                <Input
                  size="large"
                  value={tenantCode}
                  placeholder="例如 acme"
                  autoComplete="off"
                  onChange={(event) => setTenant(event.target.value)}
                />
              </Form.Item>
            )}

            <Button
              type="primary"
              htmlType="submit"
              size="large"
              loading={submitting}
              className="login-submit-btn"
            >
              {submitting ? '登录中…' : '登 录'}
            </Button>
          </Form>
        </div>
      </section>
    </div>
  )
}
