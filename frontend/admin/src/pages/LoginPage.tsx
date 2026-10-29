import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Form, Input, Select, Tag } from 'antd'
import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import { PLATFORM_TENANT_CODE } from '../tenant/scope'
import './LoginPage.css'

interface LoginFormValues {
  username: string
  password: string
}

const ENV_LABELS = {
  local: '本地',
  dev: '开发',
  test: '测试',
  prod: '线上',
} as const

const RESOLUTION_LABELS = {
  host: '按域名解析作用域',
  header: '按请求头切换作用域',
  default: '使用默认作用域',
} as const

function safeNextPath(search: string, fallback: string): string {
  const next = new URLSearchParams(search).get('next')
  if (!next || !next.startsWith('/') || next.startsWith('//') || next === '/login') {
    return fallback
  }
  return next
}

export default function LoginPage() {
  const { user, signIn } = useAuth()
  const { context, platformName, scopeLabel, isPlatform, selectableTenants, switchTenant } =
    useTenant()
  const navigate = useNavigate()
  const location = useLocation()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const currentScopeCode = isPlatform ? PLATFORM_TENANT_CODE : (context?.tenant?.code ?? '')
  const scopeOptions = [
    { label: '产品级平台', value: PLATFORM_TENANT_CODE },
    ...selectableTenants.map((tenant) => ({ label: tenant.name, value: tenant.code })),
  ]
  // 部署环境只认域名（none）；本地回环主机走 header，本地子域名走域名跳转
  const canSwitchScope = context?.tenant_switch_mode !== 'none' && isPlatform

  if (user) {
    return <Navigate to={user.must_change_password ? '/change-password' : '/apps'} replace />
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
      const next = safeNextPath(location.search, '/apps')
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
          <h1>{platformName}</h1>
          <p className="login-brand__slogan">
            {isPlatform ? '跨租户的智能体产品运营与治理' : '为本租户配置智能体、工具与技能'}
          </p>
          <ul className="login-brand__features">
            <li>可视化编排智能体，沉淀提示词、技能与工具</li>
            <li>产品级资源统一维护，租户内即取即用</li>
            <li>按子域名隔离租户，数据与账号互不可见</li>
          </ul>
        </div>
        <div className="login-brand__orb login-brand__orb--one" />
        <div className="login-brand__orb login-brand__orb--two" />
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-card__scope">
            <span>
              <Tag color={isPlatform ? 'geekblue' : 'green'}>{scopeLabel}</Tag>
              {context && context.app_env !== 'prod' && (
                <Tag color="orange">{ENV_LABELS[context.app_env]}</Tag>
              )}
            </span>
            {context?.root_domain && (
              <span className="login-card__domain">{context.root_domain}</span>
            )}
          </div>
          {context && (
            <p className="login-card__hint">{RESOLUTION_LABELS[context.tenant_resolution]}</p>
          )}
          <h2>欢迎回来</h2>
          <p className="login-card__subtitle">
            {isPlatform ? '登录产品级平台，维护全部租户' : '登录本租户平台'}
          </p>

          {canSwitchScope && (
            <Select
              className="login-card__scope-select"
              value={currentScopeCode}
              options={scopeOptions}
              onChange={switchTenant}
              placeholder="切换产品级 / 租户"
            />
          )}

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

          <p className="login-card__footer">{platformName} · 管理端</p>
        </div>
      </section>
    </div>
  )
}
