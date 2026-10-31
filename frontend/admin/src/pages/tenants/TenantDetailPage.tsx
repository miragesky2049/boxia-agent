import { ArrowLeftOutlined } from '@ant-design/icons'
import { App, Button, Descriptions, Space, Spin, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getTenant } from '../../api/tenant'
import type { Tenant } from '../../api/types'
import { useTenant } from '../../tenant/TenantContext'

export default function TenantDetailPage() {
  const { id } = useParams<{ id: string }>()
  const tenantId = id ?? ''
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { context } = useTenant()
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTenant(await getTenant(tenantId))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载租户失败')
      navigate('/tenants', { replace: true })
    } finally {
      setLoading(false)
    }
  }, [tenantId, message, navigate])

  useEffect(() => {
    if (!tenantId) {
      navigate('/tenants', { replace: true })
      return
    }
    void load()
  }, [tenantId, load, navigate])

  return (
    <div className="page-card">
      <div className="page-header">
        <Space size={12} align="center">
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/tenants')} />
          <div>
            <h2 className="page-header__title">{tenant?.name ?? '租户详情'}</h2>
            <p className="page-header__desc">
              {context?.root_domain && tenant
                ? `${tenant.code}.${context.root_domain}`
                : (tenant?.code ?? '')}
            </p>
          </div>
          {tenant && (
            <Tag color={tenant.is_active ? 'green' : 'default'} bordered={false}>
              {tenant.is_active ? '启用' : '停用'}
            </Tag>
          )}
          <Button onClick={() => navigate(`/tenants/${tenantId}/settings`)}>运行时配置</Button>
        </Space>
      </div>

      <Spin spinning={loading}>
        {tenant && (
          <Descriptions column={2} bordered size="middle">
            <Descriptions.Item label="租户名称">{tenant.name}</Descriptions.Item>
            <Descriptions.Item label="租户编码">
              <Typography.Text code>{tenant.code}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="访问域名">
              {context?.root_domain
                ? `${tenant.code}.${context.root_domain}`
                : tenant.code}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {tenant.is_active ? '启用' : '停用'}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {dayjs(tenant.created_at).format('YYYY-MM-DD HH:mm')}
            </Descriptions.Item>
            <Descriptions.Item label="更新时间">
              {dayjs(tenant.updated_at).format('YYYY-MM-DD HH:mm')}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Spin>
    </div>
  )
}
