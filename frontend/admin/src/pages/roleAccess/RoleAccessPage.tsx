import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Checkbox, Select, Space, Spin, Tabs, Tag } from 'antd'
import { rolesApi } from '../../api/access'
import type { PermissionCategory, PermissionResource, Role } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import RoleAccessMatrix from './RoleAccessMatrix'

const CATEGORY_ORDER: PermissionCategory[] = ['menu', 'page', 'button', 'tool']

const CATEGORY_LABELS: Record<PermissionCategory, string> = {
  system: '系统权限',
  menu: '菜单',
  page: '页面',
  button: '操作按钮',
  tool: '工具',
}

interface PermissionGroup {
  category: PermissionCategory
  label: string
  items: PermissionResource[]
}

function isReadonlyRole(role: Role | undefined): boolean {
  if (!role) return true
  // 超管默认拥有全部权限与资源，任何写操作后端都会 422
  return role.is_system && role.code === 'superadmin'
}

interface PermissionsPanelProps {
  roleId: string
  editable: boolean
}

function PermissionsPanel({ roleId, editable }: PermissionsPanelProps) {
  const { message } = App.useApp()
  const [catalog, setCatalog] = useState<PermissionResource[]>([])
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [savedCodes, setSavedCodes] = useState<string[]>([])
  const [activeCategory, setActiveCategory] = useState<PermissionCategory | undefined>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([rolesApi.permissions(), rolesApi.listPermissions(roleId)])
      .then(([resources, granted]) => {
        if (cancelled) return
        setCatalog(resources)
        setSelectedCodes(granted.codes)
        setSavedCodes(granted.codes)
      })
      .catch((error: unknown) => {
        if (cancelled) return
        message.error(error instanceof Error ? error.message : '加载功能权限失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [roleId, message])

  const groups = useMemo<PermissionGroup[]>(
    () =>
      CATEGORY_ORDER.map((category) => ({
        category,
        label: CATEGORY_LABELS[category],
        items: catalog
          .filter((item) => item.category === category)
          .sort((a, b) => a.sort_order - b.sort_order),
      })).filter((group) => group.items.length > 0),
    [catalog],
  )

  const activeGroup = groups.find((group) => group.category === activeCategory) ?? groups[0]
  const selectedSet = useMemo(() => new Set(selectedCodes), [selectedCodes])
  const activeCodes = activeGroup?.items.map((item) => item.code) ?? []
  const activeSelectedCount = activeCodes.filter((code) => selectedSet.has(code)).length

  const dirty = useMemo(() => {
    if (selectedCodes.length !== savedCodes.length) return true
    const saved = new Set(savedCodes)
    return selectedCodes.some((code) => !saved.has(code))
  }, [selectedCodes, savedCodes])

  const handleToggleCategory = (checked: boolean) => {
    setSelectedCodes((prev) => {
      const next = new Set(prev)
      activeCodes.forEach((code) => {
        if (checked) {
          next.add(code)
        } else {
          next.delete(code)
        }
      })
      return [...next]
    })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const result = await rolesApi.replacePermissions(roleId, selectedCodes)
      setSelectedCodes(result.codes)
      setSavedCodes(result.codes)
      message.success('功能权限已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存功能权限失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Spin spinning={loading}>
      {!editable && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="该角色为系统超级管理员，默认拥有全部功能权限，无需配置。"
        />
      )}
      {activeGroup && (
        <>
          <Tabs
            size="small"
            activeKey={activeGroup.category}
            onChange={(key) => setActiveCategory(key as PermissionCategory)}
            items={groups.map((group) => {
              const count = group.items.filter((item) => selectedSet.has(item.code)).length
              return {
                key: group.category,
                label: (
                  <span>
                    {group.label}
                    <Tag
                      color={count > 0 ? 'blue' : undefined}
                      bordered={false}
                      style={{ marginLeft: 6 }}
                    >
                      {count}/{group.items.length}
                    </Tag>
                  </span>
                ),
              }
            })}
          />
          <div className="permission-panel">
            <div className="permission-toolbar">
              <Checkbox
                checked={activeCodes.length > 0 && activeSelectedCount === activeCodes.length}
                indeterminate={activeSelectedCount > 0 && activeSelectedCount < activeCodes.length}
                disabled={!editable || activeCodes.length === 0}
                onChange={(event) => handleToggleCategory(event.target.checked)}
              >
                全选本类
              </Checkbox>
              <Space size={8}>
                {dirty && editable && (
                  <Tag color="warning" bordered={false}>
                    有未保存的更改
                  </Tag>
                )}
                {editable && (
                  <Button
                    type="primary"
                    size="small"
                    loading={saving}
                    disabled={!dirty}
                    onClick={() => void handleSave()}
                  >
                    保存
                  </Button>
                )}
              </Space>
            </div>
            <Checkbox.Group
              value={selectedCodes}
              disabled={!editable}
              style={{ width: '100%' }}
              onChange={(values) => setSelectedCodes(values.map(String))}
            >
              <div className="permission-grid">
                {activeGroup.items.map((item) => (
                  <Checkbox key={item.code} value={item.code} className="permission-item">
                    <span className="permission-item__name" title={item.description || undefined}>
                      {item.name}
                    </span>
                    <span className="permission-item__code">{item.code}</span>
                  </Checkbox>
                ))}
              </div>
            </Checkbox.Group>
          </div>
        </>
      )}
    </Spin>
  )
}

export default function RoleAccessPage() {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canGrant = hasPermission('button:role:grant')
  const [roles, setRoles] = useState<Role[]>([])
  const [roleId, setRoleId] = useState<string | undefined>(undefined)
  const [section, setSection] = useState<'permissions' | 'grants'>('grants')

  useEffect(() => {
    rolesApi
      .list()
      .then((items) => {
        setRoles(items)
        setRoleId((current) => {
          if (current && items.some((item) => item.id === current)) return current
          const preferred = items.find((item) => item.is_active && !isReadonlyRole(item))
          return preferred?.id ?? items[0]?.id
        })
      })
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载角色失败'),
      )
  }, [message])

  const role = useMemo(() => roles.find((item) => item.id === roleId), [roles, roleId])
  const readonly = isReadonlyRole(role)
  const canManage = canGrant && !readonly

  const handleRoleChange = useCallback((id: string) => {
    setRoleId(id)
  }, [])

  return (
    <div className="page-card">
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          style={{ width: 260 }}
          placeholder="选择角色"
          showSearch
          optionFilterProp="label"
          value={roleId}
          onChange={handleRoleChange}
          options={roles.map((item) => ({
            value: item.id,
            label: `${item.name}（${item.code}）${item.is_active ? '' : ' 已停用'}`,
          }))}
        />
        {role?.is_system && !readonly && <Tag bordered={false}>系统角色</Tag>}
      </Space>
      {role && (
        <Tabs
          activeKey={section}
          onChange={(key) => setSection(key as 'permissions' | 'grants')}
          items={[
            {
              key: 'permissions',
              label: '功能权限',
              children: <PermissionsPanel roleId={role.id} editable={canGrant && !readonly} />,
            },
            {
              key: 'grants',
              label: '资源授权',
              children: <RoleAccessMatrix key={role.id} roleId={role.id} canManage={canManage} />,
            },
          ]}
        />
      )}
    </div>
  )
}
