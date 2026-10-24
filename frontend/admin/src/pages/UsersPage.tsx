import { PlusOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { rolesApi } from '../api/access'
import type { User } from '../api/types'
import { usersApi } from '../api/users'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import { passwordRule } from '../utils/password'

interface CreateFormValues {
  username: string
  password: string
  display_name: string
  role_ids: number[]
  is_active: boolean
}

interface EditFormValues {
  display_name: string
  role_ids: number[]
  is_active: boolean
}

interface ResetFormValues {
  new_password: string
  confirm_password: string
}

export default function UsersPage() {
  const { message } = App.useApp()
  const { user: currentUser } = useAuth()
  const { context } = useTenant()
  const [items, setItems] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [roleOptions, setRoleOptions] = useState<{ label: string; value: number }[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<User | null>(null)
  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editForm] = Form.useForm<EditFormValues>()
  const [resetForm] = Form.useForm<ResetFormValues>()

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
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    rolesApi
      .list()
      .then((roles) =>
        setRoleOptions(
          roles
            .filter((role) => role.is_active)
            .map((role) => ({ label: role.name, value: role.id })),
        ),
      )
      .catch(() => setRoleOptions([]))
  }, [])

  const roleNames = useCallback(
    (roleIds: number[]) =>
      (roleIds.length ? roleIds : []).map(
        (roleId) =>
          roleOptions.find((option) => option.value === roleId)?.label ?? `角色 #${roleId}`,
      ),
    [roleOptions],
  )

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setSaving(true)
    try {
      await usersApi.create({
        username: values.username.trim(),
        password: values.password,
        display_name: values.display_name.trim() || values.username.trim(),
        role_ids: values.role_ids,
        is_active: values.is_active,
      })
      message.success('用户已创建')
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
      await usersApi.update(editing.id, {
        display_name: values.display_name.trim(),
        role_ids: values.role_ids,
        is_active: values.is_active,
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

  const handleToggle = async (record: User, enabled: boolean) => {
    try {
      await usersApi.update(record.id, { is_active: enabled })
      message.success(enabled ? '已启用' : '已禁用，该用户会话立即失效')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleDelete = async (record: User) => {
    try {
      await usersApi.remove(record.id)
      message.success('已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleResetPassword = async () => {
    if (!resetTarget) return
    const values = await resetForm.validateFields()
    setSaving(true)
    try {
      await usersApi.resetPassword(resetTarget.id, values.new_password)
      message.success('密码已重置，该用户所有会话已失效')
      setResetTarget(null)
      resetForm.resetFields()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重置失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<User> = [
    {
      title: '账号',
      key: 'account',
      width: 220,
      render: (_: unknown, record: User) => (
        <div>
          <div className="resource-name">
            {record.display_name || record.username}
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
      key: 'roles',
      width: 200,
      render: (_: unknown, record: User) => (
        <Space size={4} wrap>
          {roleNames(record.role_ids).map((name) => (
            <Tag key={name} color="green">
              {name}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (enabled: boolean, record: User) => (
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
      title: '最近登录',
      dataIndex: 'last_login_at',
      key: 'last_login_at',
      width: 170,
      render: (value: string | null) =>
        value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '从未登录',
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
      width: 190,
      render: (_: unknown, record: User) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setEditing(record)
              editForm.setFieldsValue({
                display_name: record.display_name,
                role_ids: record.role_ids,
                is_active: record.is_active,
              })
            }}
          >
            编辑
          </Button>
          <Button type="link" size="small" onClick={() => setResetTarget(record)}>
            重置密码
          </Button>
          <Popconfirm
            title="确认删除该用户？"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            disabled={record.id === currentUser?.id}
            onConfirm={() => handleDelete(record)}
          >
            <Button type="link" size="small" danger disabled={record.id === currentUser?.id}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">用户管理</h2>
          <p className="page-header__desc">
            租户管理员与普通用户统一为同一账号体系，通过角色赋予管理或使用权限。
          </p>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            createForm.resetFields()
            createForm.setFieldsValue({ is_active: true, display_name: '', role_ids: [] })
            setCreateOpen(true)
          }}
        >
          新建用户
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
          showTotal: (count) => `共 ${count} 个用户`,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
      />

      <Modal
        title="新建用户"
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
            label="登录账号"
            rules={[
              { required: true, message: '请输入登录账号' },
              { min: 3, max: 64, message: '账号长度为 3-64 个字符' },
            ]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名">
            <Input placeholder="留空时使用登录账号" maxLength={64} />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[
              { required: true, message: '请输入初始密码' },
              passwordRule(context?.password_policy),
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="role_ids"
            label="角色"
            rules={[{ required: true, message: '请至少选择一个角色' }]}
            extra="赋予超级管理员或管理员角色后，该账号可登录管理端。"
          >
            <Select mode="multiple" options={roleOptions} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="编辑用户"
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
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item
            name="role_ids"
            label="角色"
            rules={[{ required: true, message: '请至少选择一个角色' }]}
            extra="修改角色会立即使该用户现有会话失效。"
          >
            <Select mode="multiple" options={roleOptions} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
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
              passwordRule(context?.password_policy),
            ]}
            extra="重置后该用户所有会话立即失效。"
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
