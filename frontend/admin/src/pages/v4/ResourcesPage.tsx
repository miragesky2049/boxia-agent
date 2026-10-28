import {
  PlusOutlined,
  ShareAltOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createResource,
  deleteResource,
  grantResource,
  listResourceGrants,
  listResources,
  revokeResourceGrant,
  updateResource,
  type V4Resource,
  type V4ResourceGrant,
  type V4ResourceType,
} from '../../api/v4'
import { fetchPublicTenants } from '../../api/tenant'
import type { Tenant } from '../../api/types'

const TYPE_LABELS: Record<V4ResourceType, string> = {
  tool: '工具',
  prompt: 'Prompt',
  skill: '技能',
  knowledge: '知识',
}

const TYPE_COLORS: Record<V4ResourceType, string> = {
  tool: 'blue',
  prompt: 'green',
  skill: 'orange',
  knowledge: 'purple',
}

interface ResourceFormValues {
  name: string
  type: V4ResourceType
  configText: string
}

export default function V4ResourcesPage() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<V4Resource[]>([])
  const [activeTab, setActiveTab] = useState<'all' | V4ResourceType>('all')

  // 编辑抽屉
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<V4Resource | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm<ResourceFormValues>()

  // grant 抽屉
  const [grantOpen, setGrantOpen] = useState(false)
  const [grantingResource, setGrantingResource] = useState<V4Resource | null>(null)
  const [grants, setGrants] = useState<V4ResourceGrant[]>([])
  const [allTenants, setAllTenants] = useState<Tenant[]>([])
  const [grantingTenantId, setGrantingTenantId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const type = activeTab === 'all' ? undefined : activeTab
      const items = await listResources({ type, owner_type: 'platform' })
      setData(items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载资源失败')
    } finally {
      setLoading(false)
    }
  }, [activeTab, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    fetchPublicTenants()
      .then(setAllTenants)
      .catch(() => {})
  }, [])

  // ========== CRUD ==========
  const openCreate = () => {
    setEditing(null)
    form.setFieldsValue({ name: '', type: 'tool', configText: '{}' })
    setEditOpen(true)
  }

  const openEdit = (record: V4Resource) => {
    setEditing(record)
    form.setFieldsValue({
      name: record.name,
      type: record.type,
      configText: JSON.stringify(record.config ?? {}, null, 2),
    })
    setEditOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    let config: Record<string, unknown>
    try {
      config = values.configText.trim() ? JSON.parse(values.configText) : {}
    } catch {
      message.error('config 不是合法 JSON')
      return
    }
    setSaving(true)
    try {
      if (editing) {
        await updateResource(editing.id, { name: values.name, config })
        message.success('已保存')
      } else {
        await createResource({ type: values.type, name: values.name, config })
        message.success('已创建')
      }
      setEditOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: V4Resource) => {
    try {
      await deleteResource(record.id)
      message.success('已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleToggleEnabled = async (record: V4Resource, enabled: boolean) => {
    try {
      await updateResource(record.id, { is_enabled: enabled })
      message.success(enabled ? '已启用' : '已禁用')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  // ========== grant ==========
  const openGrants = async (record: V4Resource) => {
    setGrantingResource(record)
    setGrantOpen(true)
    setGrants([])
    setGrantingTenantId(null)
    try {
      const rows = await listResourceGrants(record.id)
      setGrants(rows)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权列表失败')
    }
  }

  const handleGrant = async () => {
    if (!grantingResource || !grantingTenantId) return
    try {
      await grantResource(grantingResource.id, grantingTenantId)
      message.success('已授权')
      setGrantingTenantId(null)
      const rows = await listResourceGrants(grantingResource.id)
      setGrants(rows)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '授权失败')
    }
  }

  const handleRevoke = async (tenantId: string) => {
    if (!grantingResource) return
    try {
      await revokeResourceGrant(grantingResource.id, tenantId)
      message.success('已撤销')
      const rows = await listResourceGrants(grantingResource.id)
      setGrants(rows)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '撤销失败')
    }
  }

  const tenantNameMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const t of allTenants) map.set(t.id, t.name)
    return map
  }, [allTenants])

  const grantedTenantIds = useMemo(
    () => new Set(grants.map((g) => g.tenant_id)),
    [grants],
  )

  const availableTenants = useMemo(
    () => allTenants.filter((t) => !grantedTenantIds.has(t.id)),
    [allTenants, grantedTenantIds],
  )

  const columns: ColumnsType<V4Resource> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string, record) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {record.id.slice(0, 8)}…
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (type: V4ResourceType) => (
        <Tag color={TYPE_COLORS[type]}>{TYPE_LABELS[type]}</Tag>
      ),
    },
    {
      title: '版本',
      dataIndex: 'version',
      width: 80,
      render: (v: number) => `v${v}`,
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      width: 90,
      render: (enabled: boolean, record) => (
        <Switch
          size="small"
          checked={enabled}
          onChange={(v) => handleToggleEnabled(record, v)}
        />
      ),
    },
    {
      title: '已废弃',
      dataIndex: 'is_deprecated',
      width: 90,
      render: (deprecated: boolean) =>
        deprecated ? <Tag color="default">已废弃</Tag> : <Tag>正常</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={<ShareAltOutlined />}
            onClick={() => openGrants(record)}
          >
            授权
          </Button>
          <Popconfirm
            title="确定删除该资源？"
            onConfirm={() => handleDelete(record)}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div className="page-card">
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          资源管理
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建资源
        </Button>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        平台级 tool / prompt / skill / knowledge 资源，通过授权开放给租户使用。
      </Typography.Paragraph>

      <Tabs
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as typeof activeTab)}
        items={[
          { key: 'all', label: '全部' },
          ...(Object.keys(TYPE_LABELS) as V4ResourceType[]).map((t) => ({
            key: t,
            label: TYPE_LABELS[t],
          })),
        ]}
      />

      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={data}
        pagination={{ pageSize: 20, size: 'small' }}
      />

      {/* 新建/编辑抽屉 */}
      <Drawer
        open={editOpen}
        width={560}
        title={editing ? '编辑资源' : '新建资源'}
        onClose={() => setEditOpen(false)}
        extra={
          <Button type="primary" loading={saving} onClick={handleSave}>
            保存
          </Button>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="名称"
            name="name"
            rules={[{ required: true, message: '请输入资源名称' }]}
          >
            <Input placeholder="例如：快递查询工具" />
          </Form.Item>
          <Form.Item
            label="类型"
            name="type"
            rules={[{ required: true }]}
          >
            <Select
              options={(Object.keys(TYPE_LABELS) as V4ResourceType[]).map((t) => ({
                value: t,
                label: TYPE_LABELS[t],
              }))}
              disabled={!!editing}
            />
          </Form.Item>
          <Form.Item
            label="配置（JSON）"
            name="configText"
            rules={[{ required: true }]}
            extra="不同类型的资源 config 结构不同，例如 tool 包含 endpoint / parameters"
          >
            <Input.TextArea rows={14} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
        </Form>
      </Drawer>

      {/* 授权抽屉 */}
      <Drawer
        open={grantOpen}
        width={480}
        title={grantingResource ? `授权：${grantingResource.name}` : '资源授权'}
        onClose={() => setGrantOpen(false)}
      >
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Select
            style={{ flex: 1 }}
            placeholder="选择要授权的租户"
            value={grantingTenantId ?? undefined}
            onChange={(v) => setGrantingTenantId(v)}
            options={availableTenants.map((t) => ({
              value: t.id,
              label: `${t.name}（${t.code}）`,
            }))}
          />
          <Button type="primary" onClick={handleGrant} disabled={!grantingTenantId}>
            授权
          </Button>
        </Space.Compact>

        <Typography.Text strong>已授权租户（{grants.length}）</Typography.Text>
        <Table
          style={{ marginTop: 8 }}
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={grants}
          columns={[
            {
              title: '租户',
              dataIndex: 'tenant_id',
              render: (tid: string) =>
                tenantNameMap.get(tid) ?? tid.slice(0, 8) + '…',
            },
            {
              title: '授权时间',
              dataIndex: 'granted_at',
              width: 170,
              render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
            },
            {
              title: '操作',
              key: 'actions',
              width: 80,
              render: (_: unknown, record: V4ResourceGrant) => (
                <Popconfirm title="确定撤销授权？" onConfirm={() => handleRevoke(record.tenant_id)}>
                  <Button type="link" size="small" danger>
                    撤销
                  </Button>
                </Popconfirm>
              ),
            },
          ]}
        />
      </Drawer>
    </div>
  )
}
