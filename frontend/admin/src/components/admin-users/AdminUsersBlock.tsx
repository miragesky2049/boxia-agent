import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useState } from 'react'
import type {
  AdminUser,
  AdminUserCreatePayload,
  AdminUserUpdatePayload,
  PasswordPolicy,
  Role,
} from '../../api/types'
import { passwordRule } from '../../utils/password'
import { FormSection } from '../common/FormSection'

interface CreateFormValues {
  username: string
  display_name: string
  password: string
  role_id?: string
}

interface EditFormValues {
  display_name: string
  role_id?: string
}

interface ResetFormValues {
  new_password: string
  confirm_password: string
}

export interface AdminUsersPagination {
  page: number
  pageSize: number
  total: number
  onChange: (page: number, pageSize: number) => void
}

export interface AdminUsersBlockProps {
  roles?: Role[]
  passwordPolicy?: PasswordPolicy | null
  currentUserId: string | null
  canCreate: boolean
  canUpdate: boolean
  canDelete: boolean
  canResetPassword: boolean
  dataSource: AdminUser[]
  loading: boolean
  pagination: AdminUsersPagination
  onSearch: (keyword: string) => void
  onCreate: (payload: AdminUserCreatePayload) => Promise<void>
  onUpdate: (id: string, payload: AdminUserUpdatePayload) => Promise<void>
  onRemove: (id: string) => Promise<void>
  onResetPassword: (id: string, newPassword: string) => Promise<void>
  onToggleActive: (id: string, enabled: boolean) => Promise<void>
  roleLabel?: string
  /** 隐藏新建/编辑弹窗中的角色选择（产品级租户管理固定绑定超级管理员）。 */
  hideRoleSelect?: boolean
  extraHeader?: React.ReactNode
}

export function AdminUsersBlock({
  roles = [],
  passwordPolicy,
  currentUserId,
  canCreate,
  canUpdate,
  canDelete,
  canResetPassword,
  dataSource,
  loading,
  pagination,
  onSearch,
  onCreate,
  onUpdate,
  onRemove,
  onResetPassword,
  onToggleActive,
  roleLabel = '角色',
  hideRoleSelect = false,
  extraHeader,
}: AdminUsersBlockProps) {
  const { message } = App.useApp()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<AdminUser | null>(null)
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null)
  const [saving, setSaving] = useState(false)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editForm] = Form.useForm<EditFormValues>()
  const [resetForm] = Form.useForm<ResetFormValues>()

  const showActions = canUpdate || canDelete || canResetPassword

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setSaving(true)
    try {
      await onCreate({
        username: values.username.trim(),
        display_name: values.display_name.trim(),
        password: values.password,
        // 产品级入口不选角色，服务端固定绑定超级管理员
        ...(hideRoleSelect ? {} : { role_id: values.role_id }),
      })
      message.success('账号已创建，首次登录需修改密码')
      setCreateOpen(false)
      createForm.resetFields()
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
      await onUpdate(editing.id, {
        display_name: values.display_name.trim(),
        ...(hideRoleSelect ? {} : { role_id: values.role_id }),
      })
      message.success('已保存')
      setEditing(null)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (record: AdminUser, enabled: boolean) => {
    try {
      await onToggleActive(record.id, enabled)
      message.success(enabled ? '已启用' : '已禁用，相关会话立即失效')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleDelete = async (record: AdminUser) => {
    try {
      await onRemove(record.id)
      message.success('已删除')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleResetPassword = async () => {
    if (!resetTarget) return
    const values = await resetForm.validateFields()
    setSaving(true)
    try {
      await onResetPassword(resetTarget.id, values.new_password)
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
      render: (_, record) => (
        <div>
          <div className="resource-name">
            {record.display_name}
            {record.id === currentUserId && (
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
      title: roleLabel,
      key: 'role',
      width: 160,
      render: (_, record) => (
        <div>
          <Tag color="green">{record.role_name || '-'}</Tag>
          <div className="resource-desc">{record.role_code}</div>
        </div>
      ),
    },
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
      render: (enabled: boolean, record) => (
        <Switch
          size="small"
          checked={enabled}
          checkedChildren="启用"
          unCheckedChildren="禁用"
          disabled={!canUpdate || record.id === currentUserId}
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
    ...(showActions
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 220,
            render: (_: unknown, record: AdminUser) => (
              <Space size={4}>
                {canUpdate && (
                  <Button
                    type="link"
                    size="small"
                    onClick={() => {
                      setEditing(record)
                      editForm.setFieldsValue({
                        display_name: record.display_name,
                        role_id: record.role_id ?? undefined,
                      })
                    }}
                  >
                    编辑
                  </Button>
                )}
                {canResetPassword && (
                  <Button type="link" size="small" onClick={() => setResetTarget(record)}>
                    重置密码
                  </Button>
                )}
                {canDelete && (
                  <Popconfirm
                    title="确认删除该管理员？"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    disabled={record.id === currentUserId}
                    onConfirm={() => handleDelete(record)}
                  >
                    <Button type="link" size="small" danger disabled={record.id === currentUserId}>
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
    <>
      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索账号或显示名"
          style={{ width: 280 }}
          onSearch={(value) => onSearch(value.trim())}
        />
        {canCreate && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            style={{ marginLeft: 8 }}
            onClick={() => {
              createForm.resetFields()
              setCreateOpen(true)
            }}
          >
            新建账号
          </Button>
        )}
        {extraHeader}
      </div>

      <Table<AdminUser>
        rowKey="id"
        columns={columns}
        dataSource={dataSource}
        loading={loading}
        pagination={{
          current: pagination.page,
          pageSize: pagination.pageSize,
          total: pagination.total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (count) => `共 ${count} 个账号`,
          onChange: pagination.onChange,
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
          <FormSection title="账号信息" description="登录账号与初始密码，首次登录需修改">
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
              rules={[{ required: true, message: '请输入初始密码' }, passwordRule(passwordPolicy)]}
              extra="管理员首次登录后必须修改密码。"
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
          </FormSection>

          {!hideRoleSelect && (
            <FormSection title="角色配置">
              <Form.Item
                name="role_id"
                label={roleLabel}
                rules={[{ required: true, message: `请选择${roleLabel}` }]}
              >
                <Select options={roles.map((role) => ({ label: role.name, value: role.id }))} />
              </Form.Item>
            </FormSection>
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
          {!hideRoleSelect && (
            <Form.Item
              name="role_id"
              label={roleLabel}
              rules={[{ required: true, message: `请选择${roleLabel}` }]}
              extra="修改角色会立即刷新该账号的权限与会话。"
            >
              <Select options={roles.map((role) => ({ label: role.name, value: role.id }))} />
            </Form.Item>
          )}
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
            rules={[{ required: true, message: '请输入新密码' }, passwordRule(passwordPolicy)]}
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
    </>
  )
}
