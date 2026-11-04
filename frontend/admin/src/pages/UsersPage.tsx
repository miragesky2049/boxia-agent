import { PlusOutlined } from '@ant-design/icons'
import { App, Button, DatePicker, Divider, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, TreeSelect } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { departmentsApi } from '../api/department'
import type { Department, User } from '../api/types'
import { usersApi } from '../api/users'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import { buildDepartmentTreeData } from '../utils/departmentTree'
import { passwordRule } from '../utils/password'

interface CreateFormValues {
  username: string
  password: string
  display_name: string
  is_active: boolean
  employee_no?: string | null
  phone?: string | null
  email?: string | null
  gender?: string | null
  birth_date?: dayjs.Dayjs | null
  avatar_url?: string
  remark?: string
}

interface EditFormValues {
  display_name: string
  is_active: boolean
  employee_no?: string | null
  phone?: string | null
  email?: string | null
  gender?: string | null
  birth_date?: dayjs.Dayjs | null
  avatar_url?: string
  remark?: string
}

interface ResetFormValues {
  new_password: string
  confirm_password: string
}

const genderOptions = [
  { label: '男', value: 'male' },
  { label: '女', value: 'female' },
  { label: '未知', value: 'unknown' },
]

export default function UsersPage() {
  const { message } = App.useApp()
  const { user: currentUser, hasPermission } = useAuth()
  const canCreate = hasPermission('button:user:create')
  const canUpdate = hasPermission('button:user:update')
  const canDelete = hasPermission('button:user:delete')
  const showActions = canUpdate || canDelete
  const { context, isPlatform } = useTenant()
  const [items, setItems] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [departmentTree, setDepartmentTree] = useState<Department[]>([])
  const [filterDepartmentId, setFilterDepartmentId] = useState<string | undefined>(undefined)
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
        department_id: filterDepartmentId,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, filterDepartmentId, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (isPlatform) return
    departmentsApi
      .tree()
      .then(setDepartmentTree)
      .catch(() => setDepartmentTree([]))
  }, [isPlatform])

  const departmentTreeData = useMemo(
    () => buildDepartmentTreeData(departmentTree),
    [departmentTree],
  )

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setSaving(true)
    try {
      await usersApi.create({
        username: values.username.trim(),
        password: values.password,
        display_name: values.display_name?.trim() || values.username.trim(),
        is_active: values.is_active,
        employee_no: values.employee_no?.trim() || null,
        phone: values.phone?.trim() || null,
        email: values.email?.trim() || null,
        gender: values.gender || null,
        birth_date: values.birth_date?.format('YYYY-MM-DD') || null,
        avatar_url: values.avatar_url || '',
        remark: values.remark || '',
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
        is_active: values.is_active,
        employee_no: values.employee_no?.trim() || null,
        phone: values.phone?.trim() || null,
        email: values.email?.trim() || null,
        gender: values.gender || null,
        birth_date: values.birth_date?.format('YYYY-MM-DD') || null,
        avatar_url: values.avatar_url || '',
        remark: values.remark || '',
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
      title: '用户账号',
      key: 'account',
      width: 220,
      render: (_: unknown, record: User) => (
        <div>
          <div className="resource-name">
            {record.username}
            {record.id === currentUser?.id && (
              <Tag color="green" bordered={false} style={{ marginLeft: 8 }}>
                当前账号
              </Tag>
            )}
          </div>
          {record.display_name && record.display_name !== record.username && (
            <div className="resource-desc">{record.display_name}</div>
          )}
        </div>
      ),
    },
    {
      title: '工号',
      dataIndex: 'employee_no',
      key: 'employee_no',
      width: 120,
      render: (value: string | null) => value || '-',
    },
    {
      title: '手机号',
      dataIndex: 'phone',
      key: 'phone',
      width: 140,
      render: (value: string | null) => value || '-',
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      width: 180,
      render: (value: string | null) => value || '-',
    },
    {
      title: '当前部门',
      key: 'current_department_name',
      width: 160,
      render: (_: unknown, record: User) => record.current_department_name || '-',
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
          disabled={!canUpdate || record.id === currentUser?.id}
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
    ...(showActions
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 190,
            render: (_: unknown, record: User) => (
              <Space size={4}>
                {canUpdate && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => {
                      setEditing(record)
                      editForm.setFieldsValue({
                        display_name: record.display_name,
                        is_active: record.is_active,
                        employee_no: record.employee_no,
                        phone: record.phone,
                        email: record.email,
                        gender: record.gender,
                        birth_date: record.birth_date ? dayjs(record.birth_date) : null,
                        avatar_url: record.avatar_url,
                        remark: record.remark,
                      })
                    }}
                  >
                    编辑
                  </Button>
                )}
                {canUpdate && (
                  <Button type="link" size="small" onClick={() => setResetTarget(record)}>
                    重置密码
                  </Button>
                )}
                {canDelete && (
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
                )}
              </Space>
            ),
          },
        ]
      : []),
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">用户管理</h2>
          <p className="page-header__desc">
            维护租户内用户的基本信息；角色与管理单元授权在「用户授权」页面配置。
          </p>
        </div>
        {canCreate && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              createForm.resetFields()
              createForm.setFieldsValue({ is_active: true, display_name: '' })
              setCreateOpen(true)
            }}
          >
            新建用户
          </Button>
        )}
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
        {!isPlatform && (
          <TreeSelect
            allowClear
            style={{ width: 240 }}
            placeholder="按部门筛选（含下级）"
            treeData={departmentTreeData}
            onChange={(value: string | undefined) => {
              setFilterDepartmentId(value)
              setPage(1)
            }}
          />
        )}
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
        width={640}
        forceRender
      >
        <Form<CreateFormValues> form={createForm} layout="vertical">
          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            账号信息
          </Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
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
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="禁用" />
            </Form.Item>
          </div>

          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            个人资料
          </Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item name="employee_no" label="工号">
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item name="gender" label="性别">
              <Select options={genderOptions} allowClear />
            </Form.Item>
            <Form.Item name="birth_date" label="出生日期">
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="avatar_url" label="头像 URL">
              <Input maxLength={500} />
            </Form.Item>
          </div>

          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            联系方式
          </Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item name="phone" label="手机号">
              <Input maxLength={32} />
            </Form.Item>
            <Form.Item name="email" label="邮箱">
              <Input maxLength={128} />
            </Form.Item>
          </div>

          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            其他
          </Divider>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={3} maxLength={1000} />
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
        width={640}
        forceRender
      >
        <Form<EditFormValues> form={editForm} layout="vertical">
          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            账号信息
          </Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item label="登录账号">
              <Input value={editing?.username ?? ''} disabled />
            </Form.Item>
            <Form.Item
              name="display_name"
              label="显示名"
              rules={[{ required: true, message: '请输入显示名' }]}
            >
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="禁用" />
            </Form.Item>
          </div>

          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            个人资料
          </Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item name="employee_no" label="工号">
              <Input maxLength={64} />
            </Form.Item>
            <Form.Item name="gender" label="性别">
              <Select options={genderOptions} allowClear />
            </Form.Item>
            <Form.Item name="birth_date" label="出生日期">
              <DatePicker style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="avatar_url" label="头像 URL">
              <Input maxLength={500} />
            </Form.Item>
          </div>

          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            联系方式
          </Divider>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
            <Form.Item name="phone" label="手机号">
              <Input maxLength={32} />
            </Form.Item>
            <Form.Item name="email" label="邮箱">
              <Input maxLength={128} />
            </Form.Item>
          </div>

          <Divider orientation="left" dashed style={{ margin: '4px 0 16px' }}>
            其他
          </Divider>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={3} maxLength={1000} />
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
