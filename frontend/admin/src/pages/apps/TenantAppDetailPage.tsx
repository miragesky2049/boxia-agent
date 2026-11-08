import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Radio,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  TreeSelect,
  Typography,
} from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { departmentsApi } from '../../api/department'
import { rolesApi } from '../../api/access'
import { usersApi } from '../../api/users'
import type { Department, Role, UserOption } from '../../api/types'
import {
  getTenantVisibility,
  putTenantVisibility,
  type VisibilitySubjectType,
  type WhitelistItem,
} from '../../api/tenantApps'
import { useAuth } from '../../auth/AuthContext'
import AdminScopePanel from './AdminScopePanel'

interface WhitelistRow {
  key: number
  subject_type: VisibilitySubjectType
  subject_id: string
  include_subtree: boolean
}

interface DeptTreeNode {
  title: string
  value: string
  children?: DeptTreeNode[]
}

function toTreeData(nodes: Department[]): DeptTreeNode[] {
  return nodes.map((node) => ({
    title: node.name,
    value: node.id,
    children: node.children ? toTreeData(node.children) : undefined,
  }))
}

const SUBJECT_TYPE_OPTIONS: Array<{ value: VisibilitySubjectType; label: string }> = [
  { value: 'DEPARTMENT', label: '部门' },
  { value: 'ROLE', label: '角色' },
  { value: 'USER', label: '用户' },
]

export default function TenantAppDetailPage() {
  const { appId = '' } = useParams()
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const { hasPermission } = useAuth()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [locked, setLocked] = useState(false)
  // 默认可读不可写：manageable 由详情接口确认后才放开编辑，避免竞态下出现可保存窗口
  const [manageable, setManageable] = useState(false)
  const [configured, setConfigured] = useState(false)
  const [visibility, setVisibility] = useState<'all' | 'whitelist'>('all')
  const [rows, setRows] = useState<WhitelistRow[]>([])
  const [deptTree, setDeptTree] = useState<DeptTreeNode[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [userOptions, setUserOptions] = useState<UserOption[]>([])

  useEffect(() => {
    let cancelled = false
    // 主数据：可见范围 + manageable，决定页面可编辑性，单独加载
    ;(async () => {
      setLoading(true)
      try {
        const detail = await getTenantVisibility(appId)
        if (cancelled) return
        setLocked(detail.visibility_lock)
        setManageable(detail.manageable !== false)
        setConfigured(detail.configured)
        setVisibility(detail.visibility)
        setRows(
          detail.whitelist.map((item, index) => ({
            key: index + 1,
            subject_type: item.subject_type,
            subject_id: item.subject_id,
            include_subtree: item.include_subtree,
          })),
        )
      } catch (error) {
        if (!cancelled) {
          message.error(error instanceof Error ? error.message : '加载可见范围配置失败')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    // 辅助下拉数据独立容错：子管理员可能缺少某些页面读权限，403 不应锁死整页编辑态
    departmentsApi
      .tree()
      .then((depts) => {
        if (!cancelled) setDeptTree(toTreeData(depts))
      })
      .catch(() => {})
    rolesApi
      .list()
      .then((roleList) => {
        if (!cancelled) setRoles(roleList.filter((role) => role.is_active))
      })
      .catch(() => {})
    usersApi
      .options()
      .then((items) => {
        if (!cancelled) setUserOptions(items)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [appId, message])

  const handleVisibilityChange = (next: 'all' | 'whitelist') => {
    if (next === visibility) return
    // 白名单切全员：已配置的白名单条目会被清空，需二次确认
    if (visibility === 'whitelist' && rows.length > 0) {
      modal.confirm({
        title: '切换为全员可见',
        content: `切换后 ${rows.length} 条白名单配置将被清空，确认切换？`,
        okText: '确认切换',
        cancelText: '取消',
        onOk: () => {
          setVisibility(next)
          setRows([])
        },
      })
      return
    }
    setVisibility(next)
  }

  const updateRow = (key: number, patch: Partial<WhitelistRow>) => {
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }

  const mergeUserOptions = (incoming: UserOption[]) => {
    setUserOptions((prev) => {
      const known = new Set(prev.map((item) => item.id))
      return [...prev, ...incoming.filter((item) => !known.has(item.id))]
    })
  }

  const handleSave = async () => {
    if (visibility === 'whitelist' && rows.length === 0) {
      message.warning('白名单为空时请切换为全员可见，或先添加白名单条目')
      return
    }
    const incomplete = visibility === 'whitelist' && rows.some((row) => !row.subject_id)
    if (incomplete) {
      message.warning('存在未选择主体的白名单条目')
      return
    }
    const whitelist: WhitelistItem[] =
      visibility === 'whitelist'
        ? rows.map((row) => ({
            subject_type: row.subject_type,
            subject_id: row.subject_id,
            include_subtree: row.subject_type === 'DEPARTMENT' ? row.include_subtree : false,
          }))
        : []
    setSaving(true)
    try {
      const result = await putTenantVisibility(appId, { visibility, whitelist })
      setConfigured(true)
      setRows(
        result.whitelist.map((item, index) => ({
          key: index + 1,
          subject_type: item.subject_type,
          subject_id: item.subject_id,
          include_subtree: item.include_subtree,
        })),
      )
      message.success('可见范围已保存')
    } catch (error) {
      const detail = error as { status?: number; message?: string }
      if (detail.status === 403) {
        message.error('平台已锁定该应用的可见范围，租户侧不可修改')
      } else {
        message.error(error instanceof Error ? error.message : '保存失败')
      }
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <Spin />
      </div>
    )
  }

  // 可编辑 = 在管理范围内 且 平台未锁定；否则整页只读
  const editable = manageable && !locked

  return (
    <div className="page-card">
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>
          返回列表
        </Button>
        <Typography.Title level={4} style={{ margin: 0 }}>
          应用配置
        </Typography.Title>
        {!configured && (
          <Typography.Text type="secondary">
            （当前按平台默认模板生效，保存后即成为本租户配置）
          </Typography.Text>
        )}
      </Space>

      {locked && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="平台已锁定该应用的可见范围，租户侧仅可查看"
        />
      )}

      {!manageable && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="你不在该应用的管理范围内，当前仅可查看配置"
        />
      )}

      <Card>
        <Tabs
          items={[
            {
              key: 'visibility',
              label: '可见范围',
              children: (
                <>
                  <Radio.Group
                    value={visibility}
                    disabled={!editable}
                    onChange={(event) => handleVisibilityChange(event.target.value)}
                    options={[
                      { value: 'all', label: '全员可见' },
                      { value: 'whitelist', label: '白名单可见' },
                    ]}
                  />

                  {visibility === 'whitelist' && (
                    <div style={{ marginTop: 24 }}>
                      {rows.map((row) => (
                        <Space
                          key={row.key}
                          style={{ display: 'flex', marginBottom: 12 }}
                          align="center"
                        >
                          <Select
                            value={row.subject_type}
                            style={{ width: 100 }}
                            disabled={!editable}
                            options={SUBJECT_TYPE_OPTIONS}
                            onChange={(type) =>
                              updateRow(row.key, { subject_type: type, subject_id: '' })
                            }
                          />
                          {row.subject_type === 'DEPARTMENT' && (
                            <TreeSelect
                              value={row.subject_id || undefined}
                              style={{ width: 320 }}
                              disabled={!editable}
                              showSearch
                              treeNodeFilterProp="title"
                              placeholder="选择部门"
                              treeData={deptTree}
                              onChange={(value: string) =>
                                updateRow(row.key, { subject_id: value })
                              }
                            />
                          )}
                          {row.subject_type === 'ROLE' && (
                            <Select
                              value={row.subject_id || undefined}
                              style={{ width: 320 }}
                              disabled={!editable}
                              showSearch
                              optionFilterProp="label"
                              placeholder="选择角色"
                              options={roles.map((role) => ({ value: role.id, label: role.name }))}
                              onChange={(value: string) =>
                                updateRow(row.key, { subject_id: value })
                              }
                            />
                          )}
                          {row.subject_type === 'USER' && (
                            <Select
                              value={row.subject_id || undefined}
                              style={{ width: 320 }}
                              disabled={!editable}
                              showSearch
                              filterOption={false}
                              placeholder="搜索并选择用户"
                              onSearch={async (keyword) => {
                                if (!keyword) return
                                mergeUserOptions(await usersApi.options(keyword))
                              }}
                              onChange={(value: string) =>
                                updateRow(row.key, { subject_id: value })
                              }
                              options={userOptions.map((user) => ({
                                value: user.id,
                                label: `${user.display_name || user.username}（${user.username}）`,
                              }))}
                            />
                          )}
                          {row.subject_type === 'DEPARTMENT' && (
                            <Space size={4}>
                              <Switch
                                size="small"
                                disabled={!editable}
                                checked={row.include_subtree}
                                onChange={(checked) =>
                                  updateRow(row.key, { include_subtree: checked })
                                }
                              />
                              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                含子部门
                              </Typography.Text>
                            </Space>
                          )}
                          {editable && (
                            <Button
                              size="small"
                              type="text"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={() =>
                                setRows((prev) => prev.filter((item) => item.key !== row.key))
                              }
                            />
                          )}
                        </Space>
                      ))}
                      {editable && (
                        <Button
                          icon={<PlusOutlined />}
                          onClick={() =>
                            setRows((prev) => [
                              ...prev,
                              {
                                key: Date.now(),
                                subject_type: 'USER',
                                subject_id: '',
                                include_subtree: false,
                              },
                            ])
                          }
                        >
                          添加白名单条目
                        </Button>
                      )}
                    </div>
                  )}

                  {editable && (
                    <Space style={{ marginTop: 24 }}>
                      <Button type="primary" loading={saving} onClick={handleSave}>
                        保存
                      </Button>
                    </Space>
                  )}
                </>
              ),
            },
            {
              key: 'admin-scope',
              label: '管理范围',
              children: (
                <AdminScopePanel
                  appId={appId}
                  canWrite={manageable && hasPermission('app:admin_scope:write')}
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
