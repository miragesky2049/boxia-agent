import { PlusOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, Modal, Select, Space, Switch, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { listTenants } from '../api/tenant'
import type { AdminRole, AdminUser, Tenant } from '../api/types'
import { createUser, listUsers, resetUserPassword, updateUser } from '../api/users'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'

const ROLE_META: Record<AdminRole, { label: string; color: string }> = {
  superadmin: { label: '超级管理员', color: 'red' },
  admin: { label: '管理员', color: 'blue' },
  viewer: { label: '只读', color: 'default' },
}

const ROLE_OPTIONS = (Object.keys(ROLE_META) as AdminRole[]).map((value) => ({
  value,
  label: ROLE_META[value].label,
}))

interface CreateFormValues {
  username: string
  display_name: string
  password: string
  role: AdminRole
  tenant_id?: number
}

interface EditFormValues {
  display_name: string
  role: AdminRole
}

interface ResetFormValues {
  new_password: string
  confirm_password: string
}

export default function UsersPage() {
  const { user: currentUser } = useAuth()
  const { isPlatform } = useTenant()
  const { message } = App.useApp()
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [items, setItems] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editForm] = Form.useForm<EditFormValues>()
  const [resetForm] = Form.useForm<ResetFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listUsers({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        all_tenants: isPlatform || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, isPlatform, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!isPlatform) {
      setTenants([])
      return
    }
    listTenants({ page: 1, page_size: 100 })
      .then((result) => setTenants(result.items))
      .catch(() => setTenants([]))
  }, [isPlatform])

  const tenantName = useCallback(
    (tenantId: number | null) => {
      if (tenantId === null) return '产品级平台'
      return tenants.find((tenant) => tenant.id === tenantId)?.name ?? `租户 #${tenantId}`
    },
    [tenants],
  )

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setSaving(true)
    try {
      await createUser({
        username: values.username.trim(),
        display_name: values.display_name.trim(),
        password: values.password,
        role: values.role,
        tenant_id: isPlatform ? values.tenant_id || null : undefined,
      })
      message.success('账号已创建，首次登录需修改密码')
      setCreateOpen(false)
      createForm.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const handleEdit = async () => {
    if (!editing) return
    const values = await editForm.validateFields()
    setSaving(true)
    try {
      await updateUser(editing.id, {
        display_name: values.display_name.trim(),
        role: values.role,
      })
      message.success('已保存')
      setEditing(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (record: AdminUser, enabled: boolean) => {
    try {
      await updateUser(record.id, { is_active: enabled })
      message.success(enabled ? '已启用' : '已禁用，相关会话立即失效')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleResetPassword = async () => {
    if (!resetTarget) return
    const values = await resetForm.validateFields()
    setSaving(true)
    try {
      await resetUserPassword(resetTarget.id, values.new_password)
      message.success('密码已重置，该账号所有会话已失效')
      setResetTarget(null)
      resetForm.resetFields()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重置失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<AdminUser> = [
    {
      title: '账号',
      key: 'account',
      width: 220,
      render: (_: unknown, record: AdminUser) => (
        <div>
          <div className="resource-name">
            {record.display_name}
            {record.id === currentUser?.id && (
              <Tag color="green" bordered={false} style={{ marginLeft: 8 }}>
                当前账号
              </Tag>
            )}
          </div>
          <div className="resource-desc">{record.username}</div>
        </div>
      ),
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 120,
      render: (role: AdminRole) => {
        const meta = ROLE_META[role]
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    ...(isPlatform
      ? [
          {
            title: '归属',
            key: 'tenant',
            width: 160,
            render: (_: unknown, record: AdminUser) =>
              record.tenant_id === null ? (
                <Tag color="geekblue">产品级</Tag>
              ) : (
                <Tag color="green">{tenantName(record.tenant_id)}</Tag>
              ),
          },
        ]
      : []),
    {
      title: '密码状态',
      dataIndex: 'must_change_password',
      key: 'must_change_password',
      width: 120,
      render: (must: boolean) =>
        must ? <Tag color="orange">待修改</Tag> : <Tag color="success">已设置</Tag>,
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (enabled: boolean, record: AdminUser) => (
        <Switch
          size="small"
          checked={enabled}
          checkedChildren="启用"
          unCheckedChildren="禁用"
          disabled={record.id === currentUser?.id}
          onChange={(checked) => handleToggle(record, checked)}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 170,
      render: (_: unknown, record: AdminUser) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditing(record)
              editForm.setFieldsValue({ display_name: record.display_name, role: record.role })
            }}
          >
            编辑
          </Button>
          <Button type="link" size="small" onClick={() => setResetTarget(record)}>
            重置密码
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">管理员管理</h2>
          <p className="page-header__desc">维护管理员账号、角色与启用状态，仅超级管理员可访问。</p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            createForm.resetFields()
            createForm.setFieldsValue({ role: 'admin', tenant_id: 0 })
            setCreateOpen(true)
          }}
        >
          新建账号
        </Button>
      </div>

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
      </div>

      <Table<AdminUser>
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
          showTotal: (count) => `共 ${count} 个账号`,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
      />

      <Modal
        title="新建管理员"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={saving}
        okText="创建"
        cancelText="取消"
        forceRender
      >
        <Form<CreateFormValues> form={createForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="username"
            label="账号"
            rules={[
              { required: true, message: '请输入账号' },
              { min: 3, max: 64, message: '账号长度为 3-64 个字符' },
            ]}
          >
            <Input placeholder="登录账号" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="display_name"
            label="显示名"
            rules={[{ required: true, message: '请输入显示名' }]}
          >
            <Input placeholder="展示在管理后台的名称" />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[
              { required: true, message: '请输入初始密码' },
              { min: 12, message: '密码至少 12 位' },
            ]}
            extra="管理员首次登录后必须修改密码。"
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
          {isPlatform && (
            <Form.Item
              name="tenant_id"
              label="归属"
              extra="产品级账号仅能登录产品级平台；租户账号只能登录对应租户子域名。"
            >
              <Select
                allowClear
                placeholder="默认归属产品级平台"
                options={[
                  { label: '产品级平台', value: 0 },
                  ...tenants.map((tenant) => ({
                    label: `${tenant.name}（${tenant.code}）`,
                    value: tenant.id,
                  })),
                ]}
              />
            </Form.Item>
          )}
        </Form>
      </Modal>

      <Modal
        title="编辑管理员"
        open={Boolean(editing)}
        onOk={handleEdit}
        onCancel={() => setEditing(null)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form<EditFormValues> form={editForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="display_name"
            label="显示名"
            rules={[{ required: true, message: '请输入显示名' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true, message: '请选择角色' }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={resetTarget ? `重置密码：${resetTarget.username}` : '重置密码'}
        open={Boolean(resetTarget)}
        onOk={handleResetPassword}
        onCancel={() => setResetTarget(null)}
        confirmLoading={saving}
        okText="重置"
        cancelText="取消"
        forceRender
      >
        <Form<ResetFormValues> form={resetForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="new_password"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 12, message: '密码至少 12 位' },
            ]}
            extra="重置后该账号需在下次登录时再次修改密码。"
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm_password"
            label="确认新密码"
            dependencies={['new_password']}
            rules={[
              { required: true, message: '请再次输入新密码' },
              ({ getFieldValue }) => ({
                validator: (_, value: string | undefined) =>
                  !value || getFieldValue('new_password') === value
                    ? Promise.resolve()
                    : Promise.reject(new Error('两次输入的密码不一致')),
              }),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
