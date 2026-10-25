import { ArrowLeftOutlined, RobotOutlined } from '@ant-design/icons'
import { Alert, App, Button, Descriptions, Space, Spin, Tabs, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getTenant, listTenantAgents } from '../../api/tenant'
import type { Tenant } from '../../api/types'
import { useTenant } from '../../tenant/TenantContext'
import TenantAgentsTab from './TenantAgentsTab'

interface AgentStats {
  total: number
  opened: number
}

export default function TenantDetailPage() {
  const { id } = useParams<{ id: string }>()
  const tenantId = id ? Number(id) : NaN
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { message } = App.useApp()
  const { context } = useTenant()
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [loading, setLoading] = useState(true)
  const [agentStats, setAgentStats] = useState<AgentStats | null>(null)
  const activeTab = searchParams.get('tab') === 'agents' ? 'agents' : 'basic'

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

  const loadStats = useCallback(async () => {
    try {
      const [all, opened] = await Promise.all([
        listTenantAgents(tenantId, { page: 1, page_size: 1 }),
        listTenantAgents(tenantId, { page: 1, page_size: 1, opened_only: true }),
      ])
      setAgentStats({ total: all.total, opened: opened.total })
    } catch {
      // 统计仅用于入口提示，失败时不阻断详情页
      setAgentStats(null)
    }
  }, [tenantId])

  useEffect(() => {
    if (Number.isNaN(tenantId)) {
      navigate('/tenants', { replace: true })
      return
    }
    void load()
    void loadStats()
  }, [tenantId, load, loadStats, navigate])

  const switchTab = (key: string) => {
    const next = new URLSearchParams(searchParams)
    if (key === 'basic') {
      next.delete('tab')
    } else {
      next.set('tab', key)
    }
    setSearchParams(next, { replace: true })
  }

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
        </Space>
        {tenant && (
          <Button
            type="primary"
            icon={<RobotOutlined />}
            onClick={() => switchTab('agents')}
          >
            开通智能体
          </Button>
        )}
      </div>

      <Spin spinning={loading}>
        <Tabs
          activeKey={activeTab}
          onChange={switchTab}
          items={[
            {
              key: 'basic',
              label: '基本信息',
              children: tenant ? (
                <>
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
                  <Alert
                    className="tenant-agent-entry"
                    type={agentStats && agentStats.opened > 0 ? 'info' : 'warning'}
                    showIcon
                    icon={<RobotOutlined />}
                    message={
                      agentStats
                        ? `已开通 ${agentStats.opened} 个智能体，平台共 ${agentStats.total} 个可用`
                        : '为该租户开通平台智能体'
                    }
                    description="开通后，租户内的角色才能被授权使用对应智能体。"
                    action={
                      <Button type="primary" size="small" onClick={() => switchTab('agents')}>
                        去开通
                      </Button>
                    }
                  />
                </>
              ) : null,
            },
            {
              key: 'agents',
              label: (
                <Space size={6}>
                  <RobotOutlined />
                  <span>开通智能体</span>
                  {agentStats && (
                    <Tag
                      bordered={false}
                      color={agentStats.opened > 0 ? 'blue' : 'default'}
                      style={{ marginInlineEnd: 0 }}
                    >
                      {agentStats.opened}/{agentStats.total}
                    </Tag>
                  )}
                </Space>
              ),
              children: tenant ? (
                <TenantAgentsTab tenantId={tenant.id} onChanged={loadStats} />
              ) : null,
            },
          ]}
        />
      </Spin>
    </div>
  )
}
