import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input } from 'antd'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import './LoginPage.css'

interface LoginFormValues {
  username: string
  password: string
}

function safeNextPath(search: string, fallback: string): string {
  const next = new URLSearchParams(search).get('next')
  if (!next || !next.startsWith('/') || next.startsWith('//') || next === '/login') {
    return fallback
  }
  return next
}

export default function LoginPage() {
  const { user, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (user) {
    return <Navigate to={user.must_change_password ? '/change-password' : '/agents'} replace />
  }

  const handleSubmit = async (values: LoginFormValues) => {
    setSubmitting(true)
    setError('')
    try {
      const profile = await signIn(values.username.trim(), values.password)
      if (profile.must_change_password) {
        navigate('/change-password', { replace: true })
        return
      }
      const next = safeNextPath(location.search, '/agents')
      navigate(next, { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        const suffix =
          err.code === 'ACCOUNT_LOCKED' && err.retryAfterSeconds
            ? `（约 ${Math.ceil(err.retryAfterSeconds / 60)} 分钟后可重试）`
            : ''
        setError(`${err.message}${suffix}`)
      } else {
        setError('登录失败，请稍后再试')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login-page">
      <section className="login-brand">
        <div className="login-brand__inner">
          <div className="login-brand__logo">B</div>
          <h1>Boxia Agent</h1>
          <p className="login-brand__slogan">企业级智能体开发与运营平台</p>
          <ul className="login-brand__features">
            <li>可视化编排智能体，沉淀提示词、技能与工具</li>
            <li>统一管理会话渠道与知识库配置</li>
            <li>开箱即用的管理后台，随时发布上线</li>
          </ul>
        </div>
        <div className="login-brand__orb login-brand__orb--one" />
        <div className="login-brand__orb login-brand__orb--two" />
      </section>

      <section className="login-panel">
        <div className="login-card">
          <h2>欢迎回来</h2>
          <p className="login-card__subtitle">登录管理后台，开始配置你的智能体</p>

          {error && <Alert className="login-card__alert" type="error" showIcon message={error} />}

          <Form<LoginFormValues>
            layout="vertical"
            size="large"
            requiredMark={false}
            onFinish={handleSubmit}
          >
            <Form.Item
              name="username"
              label="账号"
              rules={[{ required: true, message: '请输入账号' }]}
            >
              <Input prefix={<UserOutlined />} placeholder="请输入管理员账号" autoFocus />
            </Form.Item>
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="请输入登录密码" />
            </Form.Item>
            <Form.Item className="login-card__submit">
              <Button type="primary" htmlType="submit" block loading={submitting}>
                登录
              </Button>
            </Form.Item>
          </Form>

          <p className="login-card__footer">Boxia Agent · 管理端</p>
        </div>
      </section>
    </div>
  )
}
