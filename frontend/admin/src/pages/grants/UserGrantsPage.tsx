import { SafetyCertificateOutlined } from '@ant-design/icons'
import { Alert, App, Button, Form, Input, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { grantsApi, rolesApi } from '../../api/access'
import { mgmtUnitsApi } from '../../api/mgmtUnit'
import type { MgmtUnit } from '../../api/mgmtUnit'
import type { Role, User, UserOption } from '../../api/types'
import { usersApi } from '../../api/users'
import { useAuth } from '../../auth/AuthContext'
import { FormSection } from '../../components/common/FormSection'

interface GrantFormValues {
  role_ids: string[]
  mgmt_unit_ids: string[]
}

interface BatchFormValues extends GrantFormValues {
  user_ids: string[]
}

const MAX_BATCH_USERS = 200

export default function UserGrantsPage() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission('button:grant:manage')
  const { message } = App.useApp()
  const [items, setItems] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [roles, setRoles] = useState<Role[]>([])
  const [units, setUnits] = useState<MgmtUnit[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  // 行编辑状态
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [editForm] = Form.useForm<GrantFormValues>()

  // 批量授权状态
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchForm] = Form.useForm<BatchFormValues>()
  const [userOptions, setUserOptions] = useState<UserOption[]>([])
  const [userSearching, setUserSearching] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await usersApi.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载用户失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    rolesApi
      .list({ include_inactive: true })
      .then(setRoles)
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载角色失败'),
      )
  }, [message])

  useEffect(() => {
    mgmtUnitsApi
      .active()
      .then(setUnits)
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载管理单元失败'),
      )
  }, [message])

  const roleOptions = useMemo(
    () =>
      roles.filter((role) => role.is_active).map((role) => ({ label: role.name, value: role.id })),
    [roles],
  )

  const unitOptions = useMemo(
    () => units.map((unit) => ({ label: unit.name, value: unit.id })),
    [units],
  )

  const roleNames = (roleIds: string[]) =>
    roleIds.map((roleId) => {
      const role = roles.find((item) => item.id === roleId)
      if (!role) return `角色 #${roleId}`
      return role.is_active ? role.name : `${role.name}（停用）`
    })

  // 行编辑
  const openEdit = (record: User) => {
    setEditingUser(record)
    editForm.setFieldsValue({
      role_ids: record.role_ids,
      mgmt_unit_ids: record.mgmt_unit_ids,
    })
  }

  const handleEditSave = async () => {
    if (!editingUser) return
    const values = await editForm.validateFields()
    setSaving(true)
    try {
      await grantsApi.assignUserRoles({
        user_ids: [editingUser.id],
        role_ids: values.role_ids,
        mgmt_unit_ids: values.mgmt_unit_ids,
        mode: 'replace',
      })
      message.success(`已保存 ${editingUser.username} 的授权`)
      setEditingUser(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存授权失败')
    } finally {
      setSaving(false)
    }
  }

  // 批量授权
  const openBatch = () => {
    batchForm.resetFields()
    batchForm.setFieldsValue({ user_ids: [], role_ids: [], mgmt_unit_ids: [] })
    setUserOptions([])
    setBatchOpen(true)
    // 预拉一次用户选项，避免弹窗打开后空白
    void searchUsers('')
  }

  const searchUsers = async (searchKeyword: string) => {
    setUserSearching(true)
    try {
      const result = await usersApi.options(searchKeyword || undefined)
      setUserOptions(result)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载用户失败')
    } finally {
      setUserSearching(false)
    }
  }

  const handleBatchSave = async () => {
    const values = await batchForm.validateFields()
    if (values.user_ids.length > MAX_BATCH_USERS) {
      message.warning(`单次最多授权 ${MAX_BATCH_USERS} 个用户`)
      return
    }
    setSaving(true)
    try {
      await grantsApi.assignUserRoles({
        user_ids: values.user_ids,
        role_ids: values.role_ids,
        mgmt_unit_ids: values.mgmt_unit_ids,
        mode: 'replace',
      })
      message.success(`已为 ${values.user_ids.length} 个用户整体覆盖授权`)
      setBatchOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量授权失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<User> = [
    {
      title: '账号',
      key: 'account',
      width: 240,
      render: (_: unknown, record: User) => (
        <div>
          <div className="resource-name">{record.display_name || record.username}</div>
          <div className="resource-desc">{record.username}</div>
        </div>
      ),
    },
    {
      title: '当前角色',
      key: 'roles',
      render: (_: unknown, record: User) => (
        <Space size={4} wrap>
          {roleNames(record.role_ids).map((name, index) => (
            <Tag key={`${record.id}-role-${index}`} color="green">
              {name}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '管理单元',
      key: 'mgmt_units',
      render: (_: unknown, record: User) => (
        <Space size={4} wrap>
          {record.mgmt_unit_names && record.mgmt_unit_names.length > 0 ? (
            record.mgmt_unit_names.map((name, index) => (
              <Tag key={`${record.id}-unit-${index}`} color="blue">
                {name}
              </Tag>
            ))
          ) : (
            <span style={{ color: '#999' }}>-</span>
          )}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 90,
      render: (enabled: boolean) => (enabled ? <Tag color="success">启用</Tag> : <Tag>禁用</Tag>),
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      key: 'last_login_at',
      width: 170,
      render: (value: string | null) =>
        value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '从未登录',
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 100,
            render: (_: unknown, record: User) => (
              <Button type="link" size="small" onClick={() => openEdit(record)}>
                编辑
              </Button>
            ),
          },
        ]
      : []),
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">用户授权</h2>
          <p className="page-header__desc">
            为用户分配角色（功能权限）+
            管理单元（数据权限）；角色决定菜单与按钮，管理单元决定可见的智能体范围。
          </p>
        </div>
        {canManage && (
          <Button type="primary" icon={<SafetyCertificateOutlined />} onClick={openBatch}>
            批量授权
          </Button>
        )}
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="编辑与批量授权均为整体覆盖：保存后所选角色与管理单元将替换目标用户的现有授权；角色变更会立即撤销其全部会话。"
      />

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索账号或显示名"
          style={{ width: 280 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {total} 个用户
        </Tag>
      </div>

      <Table<User>
        rowKey="id"
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

      {/* 行编辑弹窗：替换单个用户的角色 + 管理单元 */}
      <Modal
        title={editingUser ? `编辑授权：${editingUser.username}` : '编辑授权'}
        open={editingUser !== null}
        onOk={() => void handleEditSave()}
        onCancel={() => setEditingUser(null)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        width={560}
        destroyOnHidden
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="保存后将整体覆盖该用户当前角色与管理单元；角色变更会撤销其全部会话。"
        />
        <Form<GrantFormValues> form={editForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="role_ids"
            label="角色（功能权限）"
            rules={[{ required: true, message: '请至少选择一个角色' }]}
          >
            <Select mode="multiple" allowClear placeholder="选择角色" options={roleOptions} />
          </Form.Item>
          <Form.Item
            name="mgmt_unit_ids"
            label="管理单元（数据权限）"
            extra="留空表示清空该用户的管理单元授权；用户将仅可见本人创建的智能体。"
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="选择管理单元（可留空）"
              options={unitOptions}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 批量授权弹窗：弹窗内多选用户 + 角色 + 管理单元，整体覆盖 */}
      <Modal
        title="批量授权"
        open={batchOpen}
        onOk={() => void handleBatchSave()}
        onCancel={() => setBatchOpen(false)}
        confirmLoading={saving}
        okText="整体覆盖授权"
        cancelText="取消"
        width={620}
        destroyOnHidden
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="保存后将整体覆盖每个目标用户的角色与管理单元；角色变更会立即撤销其全部会话。"
        />
        <Form<BatchFormValues> form={batchForm} layout="vertical" requiredMark={false}>
          <FormSection title="目标用户">
            <Form.Item
              name="user_ids"
              label={`目标用户（最多 ${MAX_BATCH_USERS} 个）`}
              rules={[{ required: true, message: '请至少选择一个用户' }]}
            >
              <Select
                mode="multiple"
                showSearch
                filterOption={false}
                onSearch={(value) => void searchUsers(value)}
                loading={userSearching}
                placeholder="输入用户名或显示名搜索"
                options={userOptions.map((user) => ({
                  label: user.display_name
                    ? `${user.display_name}（${user.username}）`
                    : user.username,
                  value: user.id,
                }))}
              />
            </Form.Item>
          </FormSection>

          <FormSection title="授权配置">
            <Form.Item
              name="role_ids"
              label="角色（功能权限）"
              rules={[{ required: true, message: '请至少选择一个角色' }]}
            >
              <Select mode="multiple" allowClear placeholder="选择角色" options={roleOptions} />
            </Form.Item>
            <Form.Item
              name="mgmt_unit_ids"
              label="管理单元（数据权限）"
              extra="留空表示清空目标用户的管理单元授权；用户将仅可见本人创建的智能体。"
            >
              <Select
                mode="multiple"
                allowClear
                placeholder="选择管理单元（可留空）"
                options={unitOptions}
              />
            </Form.Item>
          </FormSection>
        </Form>
      </Modal>
    </div>
  )
}
