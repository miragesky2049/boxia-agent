import { LockOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Form, Input, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import { passwordRule } from '../utils/password'

interface ChangePasswordFormValues {
  current_password: string
  new_password: string
  confirm_password: string
}

export default function ChangePasswordPage() {
  const { changePassword, mustChangePassword } = useAuth()
  const { context } = useTenant()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [form] = Form.useForm<ChangePasswordFormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleFinish = async (values: ChangePasswordFormValues) => {
    setSubmitting(true)
    setError('')
    try {
      await changePassword(values.current_password, values.new_password)
      void message.success('密码已修改，请使用新密码重新登录')
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '修改密码失败，请稍后再试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        minHeight: '100vh',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f5f7fa',
        padding: 16,
      }}
    >
      <Card style={{ width: 460, maxWidth: 'calc(100vw - 32px)' }}>
        <Typography.Title level={3} style={{ marginTop: 0 }}>
          修改密码
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          {mustChangePassword
            ? '当前账号为首次登录或密码已被重置，请先设置新密码。'
            : '修改成功后所有已登录会话将失效，需要重新登录。'}
        </Typography.Paragraph>

        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

        <Form<ChangePasswordFormValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          onFinish={handleFinish}
        >
          <Form.Item
            name="current_password"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              passwordRule(context?.password_policy),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) =>
                  !value || getFieldValue('new_password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致')),
              }),
            ]}
          >
            <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>
            确认修改
          </Button>
        </Form>
      </Card>
    </div>
  )
}
