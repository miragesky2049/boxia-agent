import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Input,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { rolesApi } from '../../api/access'
import type {
  PermissionCategory,
  PermissionResource,
  Role,
  RoleGrantResource,
  ResourceType,
} from '../../api/types'
import { useAuth } from '../../auth/AuthContext'

const RESOURCE_TABS: { key: ResourceType; label: string }[] = [
  { key: 'agent', label: '智能体' },
  { key: 'skill', label: '技能' },
  { key: 'tool', label: '工具' },
  { key: 'component', label: '组件' },
  { key: 'prompt', label: '提示词' },
]

const CATEGORY_ORDER: PermissionCategory[] = [
  'system',
  'menu',
  'page',
  'button',
  'agent',
  'skill',
  'tool',
  'component',
  'prompt',
]

const CATEGORY_LABELS: Record<PermissionCategory, string> = {
  system: '系统权限',
  menu: '菜单',
  page: '页面',
  button: '操作按钮',
  agent: '智能体',
  skill: '技能',
  tool: '工具',
  component: '组件',
  prompt: '提示词',
}

interface PermissionGroup {
  category: PermissionCategory
  label: string
  items: PermissionResource[]
}

type RoleDetailSection = 'permissions' | 'data'

export default function RoleDetailPage() {
  const { id } = useParams()
  const roleId = Number(id)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const [role, setRole] = useState<Role | null>(null)
  const [roleLoading, setRoleLoading] = useState(false)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [resourceType, setResourceType] = useState<ResourceType>('agent')
  const [items, setItems] = useState<RoleGrantResource[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [grantedOnly, setGrantedOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pendingIds, setPendingIds] = useState<number[]>([])
  const [catalog, setCatalog] = useState<PermissionResource[]>([])
  const [selectedCodes, setSelectedCodes] = useState<string[]>([])
  const [savedCodes, setSavedCodes] = useState<string[]>([])
  const [activeSection, setActiveSection] = useState<RoleDetailSection>('permissions')
  const [activeCategory, setActiveCategory] = useState<PermissionCategory | null>(null)
  const [permissionLoading, setPermissionLoading] = useState(false)
  const [savingPermissions, setSavingPermissions] = useState(false)

  const canGrant = hasPermission('button:role:grant')
  const isSuperAdmin = Boolean(role?.is_system && role.code === 'superadmin')
  const isPlatformRole = role?.tenant_id === null
  const readonly = isSuperAdmin || !canGrant

  const loadRole = useCallback(async () => {
    if (!Number.isFinite(roleId)) {
      message.error('角色不存在')
      navigate('/roles', { replace: true })
      return
    }
    setRoleLoading(true)
    try {
      const [detail, summary] = await Promise.all([
        rolesApi.get(roleId),
        rolesApi.grantSummary(roleId),
      ])
      setRole(detail)
      setCounts(summary.counts)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载角色失败')
    } finally {
      setRoleLoading(false)
    }
  }, [roleId, message, navigate])

  const loadPermissions = useCallback(async () => {
    if (!Number.isFinite(roleId)) return
    setPermissionLoading(true)
    try {
      const [resources, granted] = await Promise.all([
        rolesApi.permissions(),
        rolesApi.listPermissions(roleId),
      ])
      setCatalog(resources)
      setSelectedCodes(granted.codes)
      setSavedCodes(granted.codes)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载功能权限失败')
    } finally {
      setPermissionLoading(false)
    }
  }, [roleId, message])

  const loadGrants = useCallback(async () => {
    if (!Number.isFinite(roleId)) return
    setLoading(true)
    try {
      const result = await rolesApi.listGrants(roleId, {
        resource_type: resourceType,
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        granted_only: grantedOnly,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权失败')
    } finally {
      setLoading(false)
    }
  }, [roleId, resourceType, page, pageSize, keyword, grantedOnly, message])

  const refreshSummary = useCallback(async () => {
    if (!Number.isFinite(roleId)) return
    try {
      const summary = await rolesApi.grantSummary(roleId)
      setCounts(summary.counts)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权汇总失败')
    }
  }, [roleId, message])

  useEffect(() => {
    void loadRole()
    void loadPermissions()
  }, [loadRole, loadPermissions])

  useEffect(() => {
    void loadGrants()
  }, [loadGrants])

  const permissionGroups = useMemo<PermissionGroup[]>(() => {
    return CATEGORY_ORDER.map((category) => ({
      category,
      label: CATEGORY_LABELS[category],
      items: catalog
        .filter((item) => item.category === category)
        .sort((a, b) => a.sort_order - b.sort_order),
    })).filter((group) => group.items.length > 0)
  }, [catalog])

  const selectedSet = useMemo(() => new Set(selectedCodes), [selectedCodes])

  const activeGroup = useMemo<PermissionGroup | undefined>(() => {
    if (permissionGroups.length === 0) return undefined
    return (
      permissionGroups.find((group) => group.category === activeCategory) ?? permissionGroups[0]
    )
  }, [permissionGroups, activeCategory])

  const activeCodes = useMemo(
    () => activeGroup?.items.map((item) => item.code) ?? [],
    [activeGroup],
  )

  const selectedCountByCategory = useMemo(() => {
    const counts: Partial<Record<PermissionCategory, number>> = {}
    permissionGroups.forEach((group) => {
      counts[group.category] = group.items.filter((item) => selectedSet.has(item.code)).length
    })
    return counts
  }, [permissionGroups, selectedSet])

  const activeSelectedCount = activeCodes.filter((code) => selectedSet.has(code)).length

  const permissionsDirty = useMemo(() => {
    if (selectedCodes.length !== savedCodes.length) return true
    const saved = new Set(savedCodes)
    return selectedCodes.some((code) => !saved.has(code))
  }, [selectedCodes, savedCodes])

  const handleActiveGroupToggle = (checked: boolean) => {
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

  const handleToggle = async (record: RoleGrantResource, checked: boolean) => {
    setPendingIds((prev) => [...prev, record.resource_id])
    try {
      if (checked) {
        await rolesApi.addGrants(roleId, resourceType, [record.resource_id])
      } else {
        await rolesApi.removeGrant(roleId, resourceType, record.resource_id)
      }
      message.success(checked ? '已授权' : '已取消授权')
      await Promise.all([loadGrants(), refreshSummary()])
    } catch (error) {
      message.error(error instanceof Error ? error.message : '授权失败')
    } finally {
      setPendingIds((prev) => prev.filter((item) => item !== record.resource_id))
    }
  }

  const handleSavePermissions = async () => {
    setSavingPermissions(true)
    try {
      const result = await rolesApi.replacePermissions(roleId, selectedCodes)
      setSelectedCodes(result.codes)
      setSavedCodes(result.codes)
      message.success('功能权限已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存功能权限失败')
    } finally {
      setSavingPermissions(false)
    }
  }

  const columns: ColumnsType<RoleGrantResource> = [
    {
      title: '名称',
      key: 'name',
      render: (_: unknown, record: RoleGrantResource) => (
        <div>
          <div className="resource-name">
            {record.name}
            {record.is_platform && (
              <Tag color="geekblue" bordered={false} style={{ marginLeft: 8 }}>
                平台级
              </Tag>
            )}
          </div>
          {record.description && <div className="resource-desc">{record.description}</div>}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 90,
      render: (enabled: boolean) => (enabled ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '授权',
      key: 'granted',
      width: 90,
      align: 'center',
      render: (_: unknown, record: RoleGrantResource) => (
        <Checkbox
          checked={record.is_granted}
          disabled={readonly || pendingIds.includes(record.resource_id)}
          onChange={(event) => void handleToggle(record, event.target.checked)}
        >
          {record.is_granted ? '已授权' : '未授权'}
        </Checkbox>
      ),
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <Space size={8}>
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/roles')} />
            <h2 className="page-header__title">{role?.name ?? '角色授权'}</h2>
          </Space>
          <p className="page-header__desc">
            {isPlatformRole
              ? '功能权限决定该平台角色可使用的管理入口与操作；数据授权决定其可访问的平台级智能体、技能、工具、组件与提示词。'
              : '功能权限决定该角色可使用的管理入口与操作；数据授权决定其可访问的智能体、技能、工具、组件与提示词。'}
          </p>
        </div>
      </div>

      {role && (
        <Card size="small" loading={roleLoading} style={{ marginBottom: 16 }}>
          <Descriptions column={3} size="small">
            <Descriptions.Item label="角色编码">{role.code}</Descriptions.Item>
            <Descriptions.Item label="类型">
              {role.is_system ? <Tag color="gold">系统角色</Tag> : <Tag>自定义角色</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {role.is_active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="描述" span={3}>
              {role.description || '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <Card size="small">
        <Tabs
          activeKey={activeSection}
          onChange={(key) => setActiveSection(key as RoleDetailSection)}
          items={[
            {
              key: 'permissions',
              label: '功能权限',
              children: (
                <>
                  {isSuperAdmin && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message="超级管理员角色默认拥有全部功能权限，无需配置。"
                    />
                  )}
                  <Spin spinning={permissionLoading}>
                    {permissionGroups.length === 0 || !activeGroup ? (
                      <Empty description="暂无可配置的功能权限" />
                    ) : (
                      <>
                        <Tabs
                          size="small"
                          activeKey={activeGroup.category}
                          onChange={(key) => setActiveCategory(key as PermissionCategory)}
                          items={permissionGroups.map((group) => {
                            const selectedCount = selectedCountByCategory[group.category] ?? 0
                            return {
                              key: group.category,
                              label: (
                                <span>
                                  {group.label}
                                  <Tag
                                    color={selectedCount > 0 ? 'blue' : undefined}
                                    bordered={false}
                                    style={{ marginLeft: 6 }}
                                  >
                                    {selectedCount}/{group.items.length}
                                  </Tag>
                                </span>
                              ),
                            }
                          })}
                        />
                        <div className="permission-panel">
                          <div className="permission-toolbar">
                            <Checkbox
                              checked={
                                activeCodes.length > 0 && activeSelectedCount === activeCodes.length
                              }
                              indeterminate={
                                activeSelectedCount > 0 && activeSelectedCount < activeCodes.length
                              }
                              disabled={readonly || activeCodes.length === 0}
                              onChange={(event) => handleActiveGroupToggle(event.target.checked)}
                            >
                              全选本类
                            </Checkbox>
                            <span className="permission-summary">
                              本类已选 {activeSelectedCount} / {activeCodes.length} 项 · 全部已选{' '}
                              {selectedCodes.length} 项
                            </span>
                            {canGrant && !isSuperAdmin && (
                              <Space size={8} className="permission-toolbar__actions">
                                {permissionsDirty && (
                                  <Tag color="warning" bordered={false}>
                                    有未保存的更改
                                  </Tag>
                                )}
                                <Button
                                  type="primary"
                                  size="small"
                                  icon={<SaveOutlined />}
                                  loading={savingPermissions}
                                  disabled={!permissionsDirty}
                                  onClick={() => void handleSavePermissions()}
                                >
                                  保存
                                </Button>
                              </Space>
                            )}
                          </div>
                          <Checkbox.Group
                            value={selectedCodes}
                            disabled={readonly}
                            style={{ width: '100%' }}
                            onChange={(values) => setSelectedCodes(values.map(String))}
                          >
                            <div className="permission-grid">
                              {activeGroup.items.map((item) => (
                                <Checkbox
                                  key={item.code}
                                  value={item.code}
                                  className="permission-item"
                                >
                                  <span
                                    className="permission-item__name"
                                    title={item.description || undefined}
                                  >
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
                </>
              ),
            },
            {
              key: 'data',
              label: '数据授权',
              children: (
                <>
                  {isSuperAdmin && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      message={
                        isPlatformRole
                          ? '超级管理员角色默认拥有全部平台级资源，数据授权只读。'
                          : '超级管理员角色默认拥有本租户全部资源，数据授权只读。'
                      }
                    />
                  )}
                  <Tabs
                    size="small"
                    activeKey={resourceType}
                    items={RESOURCE_TABS.map((tab) => ({
                      key: tab.key,
                      label: (
                        <span>
                          {tab.label}
                          <Tag bordered={false} style={{ marginLeft: 6 }}>
                            {counts[tab.key] ?? 0}
                          </Tag>
                        </span>
                      ),
                    }))}
                    onChange={(key) => {
                      setResourceType(key as ResourceType)
                      setPage(1)
                      setKeyword('')
                      setGrantedOnly(false)
                    }}
                  />

                  <div className="page-toolbar">
                    <Input.Search
                      key={resourceType}
                      allowClear
                      placeholder="搜索名称或描述"
                      style={{ width: 260 }}
                      onSearch={(value) => {
                        setKeyword(value.trim())
                        setPage(1)
                      }}
                    />
                    <Space size={8}>
                      <Switch
                        size="small"
                        checked={grantedOnly}
                        onChange={(checked) => {
                          setGrantedOnly(checked)
                          setPage(1)
                        }}
                      />
                      <span>仅看已授权</span>
                    </Space>
                    <Tag color="blue" bordered={false}>
                      共 {total} 个
                    </Tag>
                  </div>

                  <Table<RoleGrantResource>
                    rowKey="resource_id"
                    columns={columns}
                    dataSource={items}
                    loading={loading}
                    pagination={{
                      current: page,
                      pageSize,
                      total,
                      showSizeChanger: true,
                      pageSizeOptions: ['10', '20', '50'],
                      showTotal: (count) => `共 ${count} 条`,
                      onChange: (nextPage, nextSize) => {
                        setPage(nextSize !== pageSize ? 1 : nextPage)
                        setPageSize(nextSize)
                      },
                    }}
                  />
                </>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
