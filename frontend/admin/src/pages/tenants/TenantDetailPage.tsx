import { ArrowLeftOutlined } from '@ant-design/icons'
import { App, Button, Descriptions, Space, Spin, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getTenant } from '../../api/tenant'
import { tenantAdminsApi } from '../../api/tenantAdmins'
import type { AdminUser, Tenant } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { AdminUsersBlock } from '../../components/admin-users/AdminUsersBlock'
import { FormSection } from '../../components/common/FormSection'
import { useTenant } from '../../tenant/TenantContext'

export default function TenantDetailPage() {
  const { id } = useParams<{ id: string }>()
  const tenantId = id ?? ''
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { context } = useTenant()
  const { user: currentUser, hasPermission } = useAuth()
  const [tenant, setTenant] = useState<Tenant | null>(null)
  const [loading, setLoading] = useState(true)
  const [admins, setAdmins] = useState<AdminUser[]>([])
  const [adminsTotal, setAdminsTotal] = useState(0)
  const [adminsPage, setAdminsPage] = useState(1)
  const [adminsPageSize, setAdminsPageSize] = useState(10)
  const [adminsKeyword, setAdminsKeyword] = useState('')
  const [adminsLoading, setAdminsLoading] = useState(false)

  const canCreate = hasPermission('button:admin-user:create')
  const canUpdate = hasPermission('button:admin-user:update')
  const canDelete = hasPermission('button:admin-user:delete')
  const canResetPassword = hasPermission('button:admin-user:reset-password')

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

  const loadAdmins = useCallback(async () => {
    setAdminsLoading(true)
    try {
      const result = await tenantAdminsApi.list(tenantId, {
        page: adminsPage,
        page_size: adminsPageSize,
        keyword: adminsKeyword || undefined,
      })
      setAdmins(result.items)
      setAdminsTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载管理员失败')
    } finally {
      setAdminsLoading(false)
    }
  }, [tenantId, adminsPage, adminsPageSize, adminsKeyword, message])

  useEffect(() => {
    if (!tenantId || !tenant || tenant.is_platform) return
    void loadAdmins()
  }, [tenantId, loadAdmins, tenant])

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

      {tenant && !tenant.is_platform && (
        <div style={{ marginTop: 16 }}>
          <FormSection
            title="管理员账号"
            description="维护本租户的管理端访问账号；新建账号首次登录需修改密码"
          >
            <AdminUsersBlock
              hideRoleSelect
              passwordPolicy={context?.password_policy}
              currentUserId={currentUser?.id ?? null}
              canCreate={canCreate}
              canUpdate={canUpdate}
              canDelete={canDelete}
              canResetPassword={canResetPassword}
              dataSource={admins}
              loading={adminsLoading}
              pagination={{
                page: adminsPage,
                pageSize: adminsPageSize,
                total: adminsTotal,
                onChange: (nextPage, nextSize) => {
                  setAdminsPage(nextSize !== adminsPageSize ? 1 : nextPage)
                  setAdminsPageSize(nextSize)
                },
              }}
              onSearch={(value) => {
                setAdminsKeyword(value)
                setAdminsPage(1)
              }}
              onCreate={async (payload) => {
                await tenantAdminsApi.create(tenantId, payload)
                await loadAdmins()
              }}
              onUpdate={async (id, payload) => {
                await tenantAdminsApi.update(tenantId, id, payload)
                await loadAdmins()
              }}
              onRemove={async (id) => {
                await tenantAdminsApi.remove(tenantId, id)
                await loadAdmins()
              }}
              onResetPassword={async (id, password) => {
                await tenantAdminsApi.resetPassword(tenantId, id, password)
              }}
              onToggleActive={async (id, enabled) => {
                await tenantAdminsApi.update(tenantId, id, { is_active: enabled })
                await loadAdmins()
              }}
              roleLabel="租户角色"
            />
          </FormSection>
        </div>
      )}
    </div>
  )
}
