import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  batchDeleteTenants,
  createTenant,
  deleteTenant,
  listTenants,
  updateTenant,
} from '../api/tenant'
import type { Tenant, TenantBatchDeleteItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { FormSection } from '../components/common/FormSection'
import { useTenant } from '../tenant/TenantContext'
import { passwordRule } from '../utils/password'

const PLATFORM_TENANT_CODE = 'platform'

const DELETE_SCOPE_DESC =
  '将永久删除该租户的账号、组织架构、应用开通、会话与用量等全部数据且不可恢复；平台应用本体不受影响。'

interface CreateFormValues {
  code: string
  name: string
  admin_username: string
  admin_display_name: string
  admin_password: string
}

interface EditFormValues {
  name: string
}

export default function TenantsPage() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = hasPermission('button:tenant:create')
  const canUpdate = hasPermission('button:tenant:update')
  const canDelete = hasPermission('button:tenant:delete')
  const { context } = useTenant()
  const [items, setItems] = useState<Tenant[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editing, setEditing] = useState<Tenant | null>(null)
  const [editForm] = Form.useForm<EditFormValues>()
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [batchBusy, setBatchBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listTenants({
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

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setSaving(true)
    try {
      await createTenant({
        code: values.code.trim().toLowerCase(),
        name: values.name.trim(),
        admin_username: values.admin_username.trim(),
        admin_password: values.admin_password,
        admin_display_name: values.admin_display_name.trim(),
      })
      message.success('租户已创建，租户管理员首次登录需修改密码')
      setCreateOpen(false)
      createForm.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (record: Tenant, enabled: boolean) => {
    try {
      await updateTenant(record.id, { is_active: enabled })
      message.success(enabled ? '租户已启用' : '租户已停用，该租户将无法访问')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleEdit = async () => {
    if (!editing) return
    const values = await editForm.validateFields()
    const name = values.name.trim()
    if (name === editing.name) {
      setEditing(null)
      return
    }
    setSaving(true)
    try {
      await updateTenant(editing.id, { name })
      message.success('租户名称已更新')
      setEditing(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: Tenant) => {
    setDeletingId(record.id)
    try {
      await deleteTenant(record.id)
      message.success(`租户「${record.name}」已永久删除`)
      setSelectedKeys((keys) => keys.filter((key) => key !== record.id))
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    } finally {
      setDeletingId(null)
    }
  }

  const showBatchFailures = (failed: TenantBatchDeleteItem[]) => {
    modal.error({
      title: `${failed.length} 个租户删除失败`,
      content: (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {failed.map((item) => (
            <li key={item.tenant_id}>
              {item.code ?? item.tenant_id}：{item.error ?? '未知错误'}
            </li>
          ))}
        </ul>
      ),
      okText: '知道了',
    })
  }

  const handleBatchDelete = () => {
    const targets = items.filter(
      (item) =>
        selectedKeys.includes(item.id) && !(item.is_platform ?? item.code === PLATFORM_TENANT_CODE),
    )
    if (targets.length === 0) return
    modal.confirm({
      title: `确认永久删除选中的 ${targets.length} 个租户？`,
      content: DELETE_SCOPE_DESC,
      okText: '永久删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setBatchBusy(true)
        try {
          const result = await batchDeleteTenants(targets.map((item) => item.id))
          if (result.failed === 0) {
            message.success(`已永久删除 ${result.succeeded} 个租户`)
          } else {
            message.warning(`成功 ${result.succeeded} 个，失败 ${result.failed} 个`)
            showBatchFailures(result.items.filter((item) => !item.success))
          }
          setSelectedKeys([])
          await load()
        } catch (error) {
          message.error(error instanceof Error ? error.message : '批量删除失败')
        } finally {
          setBatchBusy(false)
        }
      },
    })
  }

  const columns: ColumnsType<Tenant> = [
    {
      title: '租户',
      key: 'tenant',
      width: 260,
      render: (_: unknown, record: Tenant) => (
        <div>
          <div className="resource-name">
            {record.name}
            {record.is_platform && (
              <Tag color="gold" style={{ marginLeft: 8 }} bordered={false}>
                产品级
              </Tag>
            )}
          </div>
          <div className="resource-desc">
            {context?.root_domain ? `${record.code}.${context.root_domain}` : record.code}
          </div>
        </div>
      ),
    },
    {
      title: '编码',
      dataIndex: 'code',
      key: 'code',
      width: 140,
      render: (code: string) => <Typography.Text code>{code}</Typography.Text>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 140,
      render: (enabled: boolean, record: Tenant) => (
        <Switch
          size="small"
          checked={enabled}
          checkedChildren="启用"
          unCheckedChildren="停用"
          disabled={!canUpdate || record.is_platform}
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
      width: 220,
      render: (_: unknown, record: Tenant) => {
        const isPlatformTenant = record.is_platform ?? record.code === PLATFORM_TENANT_CODE
        return (
          <Space size={4}>
            <Button type="link" size="small" onClick={() => navigate(`/tenants/${record.id}`)}>
              详情
            </Button>
            {canUpdate && !isPlatformTenant && (
              <Button
                type="link"
                size="small"
                onClick={() => {
                  setEditing(record)
                  editForm.setFieldsValue({ name: record.name })
                }}
              >
                编辑
              </Button>
            )}
            {canDelete && (
              <Popconfirm
                title={`确认删除租户「${record.name}」？`}
                description={DELETE_SCOPE_DESC}
                okText="永久删除"
                okButtonProps={{ danger: true, loading: deletingId === record.id }}
                cancelText="取消"
                disabled={isPlatformTenant}
                onConfirm={() => handleDelete(record)}
              >
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={isPlatformTenant}
                  title={isPlatformTenant ? '系统内置租户不可删除' : undefined}
                >
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        )
      },
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">租户管理</h2>
          <p className="page-header__desc">
            创建租户并分配子域名，租户内资源与管理员账号彼此隔离；仅产品级平台可维护。
          </p>
        </div>
        {canCreate && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              createForm.resetFields()
              setCreateOpen(true)
            }}
          >
            新建租户
          </Button>
        )}
      </div>

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索租户名称或编码"
          style={{ width: 280 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
            setSelectedKeys([])
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {total} 个租户
        </Tag>
        {canDelete && selectedKeys.length > 0 && (
          <Button danger icon={<DeleteOutlined />} loading={batchBusy} onClick={handleBatchDelete}>
            批量删除（{selectedKeys.length}）
          </Button>
        )}
      </div>

      <Table<Tenant>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        rowSelection={
          canDelete
            ? {
                selectedRowKeys: selectedKeys,
                onChange: (keys) => setSelectedKeys(keys as string[]),
                getCheckboxProps: (record) => ({
                  disabled: record.is_platform ?? record.code === PLATFORM_TENANT_CODE,
                }),
              }
            : undefined
        }
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
            setSelectedKeys([])
          },
        }}
      />

      <Modal
        title="新建租户"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={saving}
        okText="创建"
        cancelText="取消"
        forceRender
        width={560}
      >
        <Form<CreateFormValues>
          form={createForm}
          name="tenant-create"
          layout="vertical"
          requiredMark={false}
        >
          <FormSection title="租户信息">
            <Form.Item
              name="code"
              label="租户编码"
              extra="作为子域名前缀，创建后不可修改；仅支持小写字母、数字和短横线。"
              rules={[
                { required: true, message: '请输入租户编码' },
                {
                  pattern: /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/,
                  message: '需为 1-63 位小写字母、数字或短横线',
                },
              ]}
            >
              <Input placeholder="例如：acme" autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="name"
              label="租户名称"
              rules={[{ required: true, message: '请输入租户名称' }]}
            >
              <Input placeholder="例如：Acme 公司" />
            </Form.Item>
          </FormSection>

          <FormSection title="管理员账号" description="该租户的超级管理员，首次登录需修改密码">
            <Form.Item
              name="admin_username"
              label="租户管理员账号"
              rules={[
                { required: true, message: '请输入管理员账号' },
                { min: 3, max: 64, message: '账号长度为 3-64 个字符' },
              ]}
            >
              <Input placeholder="该租户的超级管理员登录账号" autoComplete="off" />
            </Form.Item>
            <Form.Item name="admin_display_name" label="管理员显示名">
              <Input placeholder="默认与账号相同" />
            </Form.Item>
            <Form.Item
              name="admin_password"
              label="管理员初始密码"
              rules={[
                { required: true, message: '请输入初始密码' },
                passwordRule(context?.password_policy),
              ]}
              extra="租户管理员首次登录后必须修改密码。"
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>
          </FormSection>
        </Form>
      </Modal>

      <Modal
        title="编辑租户"
        open={Boolean(editing)}
        onOk={handleEdit}
        onCancel={() => setEditing(null)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        forceRender
      >
        <Form<EditFormValues>
          form={editForm}
          name="tenant-edit"
          layout="vertical"
          requiredMark={false}
        >
          <Form.Item label="租户编码">
            <Input value={editing?.code} disabled />
          </Form.Item>
          <Form.Item
            name="name"
            label="租户名称"
            extra="仅修改展示名称，租户子域名与编码保持不变。"
            rules={[{ required: true, message: '请输入租户名称' }]}
          >
            <Input placeholder="例如：Acme 公司" maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
