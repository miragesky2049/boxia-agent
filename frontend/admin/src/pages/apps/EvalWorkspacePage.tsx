import { Button, Card, Space, Typography } from 'antd'
import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useTenant } from '../../tenant/TenantContext'
import EvalPanel from './eval/EvalPanel'

/**
 * 平台侧应用评测工作区（M4-d T-d6）：/apps/:appId/eval。
 * 评测端点组为平台管理员接口（require_platform_admin），故挂在平台应用列表入口下，
 * 不放租户域的 /tenant-apps/:appId（tenantOnly 路由）。
 */
export default function EvalWorkspacePage() {
  const { appId = '' } = useParams()
  const navigate = useNavigate()
  const { isPlatform } = useTenant()
  // 租户账号直接输 URL 时整页请求都会 403，入口之外再加一道域守卫（对齐 AppListPage 仅平台域渲染的口径）
  if (!isPlatform) return <Navigate to="/404" replace />

  return (
    <div>
      <Space style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          智能体评测
        </Typography.Title>
        <Button onClick={() => navigate('/apps')}>返回列表</Button>
      </Space>
      <Card>
        <EvalPanel applicationId={appId} />
      </Card>
    </div>
  )
}
