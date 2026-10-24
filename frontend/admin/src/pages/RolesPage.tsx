import { PlusOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, Modal, Popconfirm, Space, Switch, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { rolesApi } from '../api/access'
import type { Role, RoleCopyPayload, RoleCreatePayload } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'

interface RoleFormValues {
  code: string
  name: string
  description?: string
  is_active: boolean
}

const SUPERADMIN_TITLE = '超级管理员角色默认拥有全部资源，不支持该操作'

export default function RolesPage() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = hasPermission('button:role:create')
  const canCopy = hasPermission('button:role:copy')
  const canUpdate = hasPermission('button:role:update')
  const canDelete = hasPermission('button:role:delete')
  const canGrant = hasPermission('button:role:grant')
  const showActions = canCopy || canUpdate || canDelete
  const { isPlatform } = useTenant()
  const [items, setItems] = useState<Role[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Role | null>(null)
  const [copying, setCopying] = useState<Role | null>(null)
  const [form] = Form.useForm<RoleFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await rolesApi.list({ include_inactive: true }))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载角色失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    setCopying(null)
    form.resetFields()
    form.setFieldsValue({
      code: '',
      name: '',
      description: '',
      is_active: true,
    })
    setModalOpen(true)
  }

  const openCopy = (record: Role) => {
    setEditing(null)
    setCopying(record)
    form.resetFields()
    form.setFieldsValue({
      code: `${record.code}-copy`.slice(0, 64),
      name: `${record.name}副本`.slice(0, 64),
      description: record.description,
      is_active: true,
    })
    setModalOpen(true)
  }

  const openEdit = (record: Role) => {
    setCopying(null)
    setEditing(record)
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      description: record.description,
      is_active: record.is_active,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await rolesApi.update(editing.id, {
          name: values.name.trim(),
          description: values.description ?? '',
          is_active: values.is_active,
        })
        message.success('角色已保存')
      } else if (copying) {
        const payload: RoleCopyPayload = {
          code: values.code.trim(),
          name: values.name.trim(),
          description: values.description ?? '',
        }
        await rolesApi.copy(copying.id, payload)
        message.success('角色已复制，授权关系已同步')
      } else {
        const payload: RoleCreatePayload = {
          code: values.code.trim(),
          name: values.name.trim(),
          description: values.description ?? '',
        }
        await rolesApi.create(payload)
        message.success('角色已创建')
      }
      setModalOpen(false)
      setEditing(null)
      setCopying(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: Role) => {
    try {
      await rolesApi.remove(record.id)
      message.success('角色已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const columns: ColumnsType<Role> = [
    {
      title: '角色',
      key: 'name',
      width: 220,
      render: (_: unknown, record: Role) => (
        <div>
          <div className="resource-name">
            {record.name}
            {record.is_system && (
              <Tag color="gold" bordered={false} style={{ marginLeft: 8 }}>
                系统角色
              </Tag>
            )}
          </div>
          <div className="resource-desc">{record.code}</div>
        </div>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (value: string) => value || '-',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (active: boolean) =>
        active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    ...(showActions || canGrant
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 240,
            render: (_: unknown, record: Role) => {
              const isSuperAdmin = record.is_system && record.code === 'superadmin'
              return (
                <Space size={4} wrap>
                  <Button
                    type="link"
                    size="small"
                    title={isSuperAdmin ? '超级管理员默认拥有全部权限，授权页只读' : undefined}
                    onClick={() => navigate(`/roles/${record.id}`)}
                  >
                    {canGrant ? '授权' : '查看'}
                  </Button>
                  {canCopy && (
                    <Button
                      type="link"
                      size="small"
                      disabled={isSuperAdmin}
                      title={isSuperAdmin ? SUPERADMIN_TITLE : undefined}
                      onClick={() => openCopy(record)}
                    >
                      复制
                    </Button>
                  )}
                  {canUpdate && (
                    <Button type="link" size="small" onClick={() => openEdit(record)}>
                      编辑
                    </Button>
                  )}
                  {canDelete && !record.is_system && (
                    <Popconfirm
                      title="确认删除该角色？"
                      description="被账号或授权引用时无法删除。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDelete(record)}
                    >
                      <Button type="link" size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              )
            },
          },
        ]
      : []),
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">角色管理</h2>
          <p className="page-header__desc">
            {isPlatform
              ? '维护产品级平台自有角色，与租户角色数据隔离；平台角色决定平台账号可访问的平台级资源。'
              : '为本租户配置自定义角色，角色决定可访问的智能体与资源范围。'}
          </p>
        </div>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建角色
          </Button>
        )}
      </div>

      <Table<Role>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={false}
      />

      <Modal
        title={copying ? '复制角色' : editing ? '编辑角色' : '新建角色'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => {
          setModalOpen(false)
          setEditing(null)
          setCopying(null)
        }}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form<RoleFormValues> form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="code"
            label="角色编码"
            rules={[
              { required: true, message: '请输入角色编码' },
              { pattern: /^[a-z0-9-]{2,64}$/, message: '仅支持小写字母、数字与短横线' },
            ]}
          >
            <Input placeholder="例如 sales" disabled={Boolean(editing)} />
          </Form.Item>
          <Form.Item
            name="name"
            label="角色名称"
            rules={[{ required: true, message: '请输入角色名称' }]}
          >
            <Input placeholder="例如 销售" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          {copying && (
            <p className="page-header__desc">
              复制会同步源角色的功能权限与资源授权，副本为可删除的自定义角色。
            </p>
          )}
          {editing && !editing.is_system && (
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
          {editing?.is_system && (
            <Form.Item name="is_active" hidden valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}
