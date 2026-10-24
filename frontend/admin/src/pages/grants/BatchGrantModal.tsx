import { App, Alert, Modal, Radio, Select, Space } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { grantsApi, rolesApi } from '../../api/access'
import { listTenants } from '../../api/tenant'
import type { GrantBatchMode, ResourceType, Role, Tenant } from '../../api/types'
import { useTenant } from '../../tenant/TenantContext'

interface BatchGrantModalProps {
  open: boolean
  resourceType: ResourceType
  resourceIds: number[]
  onClose: () => void
  onSuccess: () => void
}

type AccessScope = 'tenant' | 'roles'

const RESOURCE_LABELS: Record<ResourceType, string> = {
  agent: '智能体',
  skill: '技能',
  tool: '工具',
  component: '组件',
  prompt: '提示词',
}

export default function BatchGrantModal({
  open,
  resourceType,
  resourceIds,
  onClose,
  onSuccess,
}: BatchGrantModalProps) {
  const { message } = App.useApp()
  const { isPlatform } = useTenant()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [selectedTenant, setSelectedTenant] = useState<Tenant | null>(null)
  const [roles, setRoles] = useState<Role[]>([])
  const [mode, setMode] = useState<GrantBatchMode>('merge')
  const [accessScope, setAccessScope] = useState<AccessScope>('roles')
  const [selectedRoles, setSelectedRoles] = useState<number[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setMode('merge')
    setSelectedRoles([])
    setAccessScope(isPlatform ? 'tenant' : 'roles')
    setSelectedTenant(null)
    setRoles([])
    if (isPlatform) {
      listTenants({ page: 1, page_size: 50 })
        .then((result) => setTenants(result.items))
        .catch((error: unknown) =>
          message.error(error instanceof Error ? error.message : '加载租户失败'),
        )
      return
    }
    rolesApi
      .list({ include_inactive: true })
      .then(setRoles)
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载角色失败'),
      )
  }, [open, isPlatform, message])

  const loadTenantRoles = async (tenantId: number) => {
    try {
      const result = await rolesApi.list({ tenant_id: tenantId, include_inactive: true })
      setRoles(result)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载角色失败')
    }
  }

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
      })),
    [roles],
  )

  const modeOptions = useMemo(() => {
    if (isPlatform) {
      return [
        { label: '追加授权', value: 'merge' },
        { label: '覆盖授权', value: 'replace' },
        { label: '移除授权', value: 'clear' },
      ]
    }
    return [
      { label: '追加角色', value: 'merge' },
      { label: '覆盖授权', value: 'replace' },
      { label: '恢复默认全角色可见', value: 'clear' },
    ]
  }, [isPlatform])

  const handleSubmit = async () => {
    if (!resourceIds.length) {
      message.error('请先选择资源')
      return
    }
    if (isPlatform && !selectedTenant) {
      message.error('请选择授权租户')
      return
    }
    const needsRoles = mode !== 'clear' && (isPlatform ? accessScope === 'roles' : true)
    if (needsRoles && selectedRoles.length === 0) {
      message.error('请选择授权角色')
      return
    }

    const roleIds =
      mode === 'clear' ? [] : isPlatform && accessScope === 'tenant' ? [] : selectedRoles

    setSaving(true)
    try {
      const result = await grantsApi.batch({
        resource_type: resourceType,
        resource_ids: resourceIds,
        mode,
        tenant_id: isPlatform ? selectedTenant?.id : undefined,
        role_ids: roleIds,
      })
      message.success(`已更新 ${result.updated} 个${RESOURCE_LABELS[resourceType]}的授权`)
      onSuccess()
      onClose()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量授权失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="批量授权"
      open={open}
      onCancel={onClose}
      onOk={() => void handleSubmit()}
      okText="确认授权"
      cancelText="取消"
      confirmLoading={saving}
      width={560}
      destroyOnHidden
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message={`本次将影响已选中的 ${resourceIds.length} 个${RESOURCE_LABELS[resourceType]}`}
      />

      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <div>
          <div style={{ marginBottom: 8, fontWeight: 500 }}>操作方式</div>
          <Radio.Group
            value={mode}
            options={modeOptions}
            onChange={(event) => {
              setMode(event.target.value as GrantBatchMode)
              setSelectedRoles([])
            }}
          />
        </div>

        {isPlatform && (
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
              onChange={(value: number) => {
                const tenant = tenants.find((item) => item.id === value) ?? null
                setSelectedTenant(tenant)
                setSelectedRoles([])
                if (tenant) void loadTenantRoles(tenant.id)
              }}
            />
          </div>
        )}

        {mode !== 'clear' && (
          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>授权范围</div>
            {isPlatform ? (
              <Radio.Group
                value={accessScope}
                options={[
                  { label: '整个租户', value: 'tenant' },
                  { label: '指定角色', value: 'roles' },
                ]}
                onChange={(event) => {
                  setAccessScope(event.target.value as AccessScope)
                  setSelectedRoles([])
                }}
              />
            ) : (
              <div style={{ color: '#666' }}>仅限本租户角色</div>
            )}
          </div>
        )}

        {mode !== 'clear' && (!isPlatform || accessScope === 'roles') && (
          <div>
            <div style={{ marginBottom: 8, fontWeight: 500 }}>授权角色</div>
            <Select
              mode="multiple"
              allowClear
              placeholder="选择授权角色"
              style={{ width: '100%' }}
              options={roleOptions}
              value={selectedRoles}
              onChange={(value: number[]) => setSelectedRoles(value)}
            />
          </div>
        )}

        {mode === 'clear' && (
          <Alert
            type="warning"
            showIcon
            message={
              isPlatform
                ? '将移除所选租户对这些资源的授权，其他租户授权不受影响。'
                : '将清空授权，恢复为本租户全部角色可见。'
            }
          />
        )}
      </Space>
    </Modal>
  )
}
