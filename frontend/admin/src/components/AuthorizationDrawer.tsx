import { App, Button, Drawer, Radio, Select, Space, Spin, Tag } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { grantsApi, rolesApi } from '../api/access'
import { listTenants } from '../api/tenant'
import type { ResourceGrant, ResourceType, Role, Tenant } from '../api/types'
import { useTenant } from '../tenant/TenantContext'

interface AuthorizationDrawerProps {
  open: boolean
  onClose: () => void
  resourceType: ResourceType
  resourceId: string
  resourceName?: string
  onSaved?: () => void
}

type AccessMode = 'none' | 'tenant' | 'roles'

const RESOURCE_LABELS: Record<ResourceType, string> = {
  agent: '智能体',
  skill: '技能',
  tool: '工具',
  component: '组件',
  prompt: '提示词',
}

export default function AuthorizationDrawer({
  open,
  onClose,
  resourceType,
  resourceId,
  resourceName,
  onSaved,
}: AuthorizationDrawerProps) {
  const { message, modal } = App.useApp()
  const { isPlatform, context } = useTenant()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null)
  const [roles, setRoles] = useState<Role[]>([])
  const [accessMode, setAccessMode] = useState<AccessMode>('none')
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const tenantId = context?.tenant?.id
  const targetTenantId = isPlatform ? selectedTenant?.id : tenantId

  const applyGrants = useCallback(
    (grants: ResourceGrant[]) => {
      if (grants.length === 0) {
        setAccessMode('none')
        setSelectedRoles([])
        return
      }
      if (grants.some((grant) => grant.role_id === null)) {
        setAccessMode('tenant')
        setSelectedRoles([])
        return
      }
      setAccessMode('roles')
      setSelectedRoles(
        grants
          .map((grant) => grant.role_id)
          .filter((roleId): roleId is string => roleId !== null)
          .sort((left, right) => left.localeCompare(right)),
      )
    },
    [],
  )

  const loadAccess = useCallback(
    async (scopeTenant: string) => {
      setLoading(true)
      try {
        const [grants, roleList] = await Promise.all([
          grantsApi.list(resourceType, resourceId, scopeTenant),
          rolesApi.list({
            tenant_id: isPlatform ? scopeTenant : undefined,
            include_inactive: true,
          }),
        ])
        setRoles(roleList)
        applyGrants(grants)
      } catch (error) {
        message.error(error instanceof Error ? error.message : '加载授权失败')
      } finally {
        setLoading(false)
      }
    },
    [resourceType, resourceId, isPlatform, applyGrants, message],
  )

  useEffect(() => {
    if (!open) return
    setTenants([])
    setSelectedTenant(null)
    setRoles([])
    setAccessMode('none')
    setSelectedRoles([])
    if (!isPlatform) {
      if (tenantId) void loadAccess(tenantId)
      return
    }
    listTenants({ page: 1, page_size: 50 })
      .then((result) => setTenants(result.items))
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载租户失败'),
      )
  }, [open, isPlatform, tenantId, loadAccess, message])

  const handleTenantSearch = async (keyword: string) => {
    try {
      const result = await listTenants({
        page: 1,
        page_size: 50,
        keyword: keyword.trim() || undefined,
      })
      setTenants(result.items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载租户失败')
    }
  }

  const tenantOptions = useMemo(() => {
    const items =
      selectedTenant && !tenants.some((tenant) => tenant.id === selectedTenant.id)
        ? [selectedTenant, ...tenants]
        : tenants
    return items.map((tenant) => ({
      label: `${tenant.name}（${tenant.code}）`,
      value: tenant.id,
    }))
  }, [tenants, selectedTenant])

  const roleOptions = useMemo(
    () =>
      roles.map((role) => ({
        label: role.is_active ? role.name : `${role.name}（停用）`,
        value: role.id,
        disabled: !role.is_active,
      })),
    [roles],
  )

  const handleSave = async () => {
    if (!targetTenantId) {
      message.error('请选择授权租户')
      return
    }
    const roleIds = accessMode === 'roles' ? selectedRoles : []
    if (accessMode === 'roles' && roleIds.length === 0) {
      message.error('请选择可访问角色')
      return
    }
    if (
      accessMode === 'roles' &&
      roleIds.some((roleId) => !roles.find((role) => role.id === roleId)?.is_active)
    ) {
      message.error('已停用角色不可授权，请移除后再保存')
      return
    }

    // 整个租户授权 = 替换为空角色列表；仅“不可见”才清空
    const mode = accessMode === 'none' ? 'clear' : 'replace'
    const execute = async () => {
      setSaving(true)
      try {
        await grantsApi.batch({
          resource_type: resourceType,
          resource_ids: [resourceId],
          mode,
          tenant_id: targetTenantId,
          role_ids: roleIds,
        })
        message.success('授权已保存')
        onSaved?.()
        onClose()
      } catch (error) {
        message.error(error instanceof Error ? error.message : '保存失败')
      } finally {
        setSaving(false)
      }
    }

    if (mode === 'clear') {
      const description = isPlatform
        ? '该租户将无法再看到此资源，其他租户授权不受影响。'
        : '将清空本租户对该资源的授权，所有角色都将不可见。'
      modal.confirm({
        title: isPlatform ? '确认移除该租户的访问权限？' : '确认清空本资源授权？',
        content: description,
        okText: '确认',
        cancelText: '取消',
        onOk: execute,
      })
      return
    }
    await execute()
  }

  const renderModeOptions = () => {
    if (isPlatform) {
      return [
        { label: '该租户不可见', value: 'none' },
        { label: '整个租户', value: 'tenant' },
        { label: '指定角色', value: 'roles' },
      ]
    }
    return [
      { label: '本租户不可见', value: 'none' },
      { label: '指定角色', value: 'roles' },
    ]
  }

  return (
    <Drawer
      title={`${RESOURCE_LABELS[resourceType]}授权${resourceName ? `：${resourceName}` : ''}`}
      open={open}
      onClose={onClose}
      width={520}
      extra={
        <Button
          type="primary"
          loading={saving}
          disabled={!targetTenantId || loading}
          onClick={() => void handleSave()}
        >
          保存
        </Button>
      }
    >
      <p style={{ color: '#666', marginTop: 0 }}>
        {isPlatform
          ? '平台级资源必须显式授权；保存后仅影响所选租户，其他租户授权保持不变。'
          : '角色只能访问显式授权的资源；可授权给整个租户、指定角色，或清空授权。'}
      </p>

      {isPlatform && (
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>授权租户</div>
            <Select
              showSearch
              filterOption={false}
              placeholder="搜索并选择租户"
              style={{ width: '100%' }}
              value={selectedTenant?.id}
              options={tenantOptions}
              onSearch={(keyword) => void handleTenantSearch(keyword)}
              onChange={(value: string) => {
                const tenant = tenants.find((item) => item.id === value) ?? null
                setSelectedTenant(tenant)
                if (tenant) void loadAccess(tenant.id)
              }}
            />
          </div>
        </Space>
      )}

      {!targetTenantId ? (
        <p style={{ color: '#999', marginTop: 24 }}>请选择租户后配置授权。</p>
      ) : (
        <Spin spinning={loading}>
          <div style={{ marginTop: 24 }}>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>访问范围</div>
            <Radio.Group
              value={accessMode}
              onChange={(event) => {
                const mode = event.target.value as AccessMode
                setAccessMode(mode)
                if (mode !== 'roles') setSelectedRoles([])
              }}
              options={renderModeOptions()}
            />
          </div>

          {accessMode === 'roles' && (
            <div style={{ marginTop: 16 }}>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>可访问角色</div>
              <Select
                mode="multiple"
                allowClear
                placeholder="选择可访问的角色"
                style={{ width: '100%' }}
                options={roleOptions}
                value={selectedRoles}
                onChange={(value: string[]) => setSelectedRoles(value)}
              />
              <div style={{ color: '#999', marginTop: 6, fontSize: 12 }}>
                仅所选角色可以看到并使用该资源。
              </div>
            </div>
          )}

          {accessMode === 'tenant' && (
            <Tag color="blue" bordered={false} style={{ marginTop: 16 }}>
              {isPlatform ? '该租户内全部角色可见' : '本租户全部角色可见'}
            </Tag>
          )}

          {accessMode === 'none' && (
            <Tag bordered={false} style={{ marginTop: 16 }}>
              该租户不可见
            </Tag>
          )}
        </Spin>
      )}
    </Drawer>
  )
}
