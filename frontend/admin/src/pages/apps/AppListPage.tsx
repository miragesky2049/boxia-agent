import { CopyOutlined, DeleteOutlined, EditOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  batchDeleteApps,
  copyApp,
  createApp,
  deleteApp,
  listApps,
  setAppEnabled,
  setAppListing,
  updateApp,
  type AppBatchDeleteItem,
  type Application,
  type FlowType,
} from '../../api/apps'
import { useAuth } from '../../auth/AuthContext'
import ObjectTenantsTab from '../entitlements/ObjectTenantsTab'

const DELETE_SCOPE_DESC =
  '将永久删除应用本体及其画布版本、全部租户开通关系，以及会话、运行与用量等关联数据，且不可恢复。'

type TypeFilter = 'all' | FlowType

const FLOW_TYPE_OPTIONS: Array<{
  value: FlowType
  label: string
  desc: string
  nodes: string
  trial: string
  color: string
}> = [
  {
    value: 'agent',
    label: '智能体',
    desc: '模型自主规划与工具/知识库调用，配置面为表单、画布为事实源',
    nodes: '开始 → Agent 循环 → 结束',
    trial: '聊天试运行',
    color: '#fa541c',
  },
  {
    value: 'workflow',
    label: '工作流',
    desc: '一次输入、一次输出，适合批处理与固定流程自动化',
    nodes: '开始 → 结束',
    trial: '表单试运行',
    color: '#1677ff',
  },
  {
    value: 'chatflow',
    label: '对话流',
    desc: '多轮对话、中间输出与问答中断，适合客服与问答场景',
    nodes: '开始 → 大模型 → 输出 → 结束',
    trial: '聊天试运行',
    color: '#722ed1',
  },
]

// 0074：智能体应用编辑入口为配置页，工作流/对话流仍是画布编辑器
const editPathFor = (id: string, flowType?: FlowType) =>
  flowType === 'agent' ? `/apps/${id}/agent` : `/apps/${id}/edit`

const FLOW_TYPE_LABELS: Record<FlowType, string> = {
  workflow: '工作流',
  chatflow: '对话流',
  agent: '智能体',
}

const FLOW_TYPE_TAG_COLORS: Record<FlowType, string> = {
  workflow: 'blue',
  chatflow: 'purple',
  agent: 'orange',
}

export default function AppListPage() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const { hasPermission } = useAuth()
  const canDelete = hasPermission('button:app:delete')
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<Application[]>([])
  const [keyword, setKeyword] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('agent')
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [detailApp, setDetailApp] = useState<Application | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [batchBusy, setBatchBusy] = useState(false)

  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newFlowType, setNewFlowType] = useState<FlowType>('agent')

  // 编辑应用基本信息（名称/描述）与平台侧可见范围默认值（0068 v2）
  const [editForm] = Form.useForm<{
    name: string
    description: string
    visibility_template: 'all' | 'whitelist'
    visibility_lock: boolean
    admin_scope_mode: 'creator_only' | 'mgmt_unit' | 'all_admin'
  }>()
  const [editTarget, setEditTarget] = useState<Application | null>(null)
  const [editSaving, setEditSaving] = useState(false)
  const [copyingId, setCopyingId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const items = await listApps({ owner_type: 'platform' })
      setData(items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载应用列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase()
    return data.filter((item) => {
      if (typeFilter !== 'all' && item.flow_type !== typeFilter) return false
      return !kw || item.name.toLowerCase().includes(kw)
    })
  }, [data, keyword, typeFilter])

  const resetCreateForm = () => {
    setNewName('')
    setNewDesc('')
    setNewFlowType('agent')
  }

  const handleCreate = async (enterCanvas: boolean) => {
    if (!newName.trim()) {
      message.warning('请输入应用名称')
      return
    }
    setCreating(true)
    try {
      const result = await createApp({
        name: newName.trim(),
        description: newDesc.trim(),
        flow_type: newFlowType,
      })
      message.success('应用已创建')
      resetCreateForm()
      setCreateOpen(false)
      if (enterCanvas) {
        navigate(editPathFor(result.application_id, newFlowType))
      } else {
        void load()
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleToggleListing = async (record: Application, listed: boolean) => {
    try {
      await setAppListing(record.id, listed)
      message.success(listed ? '已上架到市场' : '已下架')
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleToggleEnabled = async (record: Application, enabled: boolean) => {
    try {
      await setAppEnabled(record.id, enabled)
      message.success(enabled ? '已启用' : '已禁用')
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleDelete = async (record: Application) => {
    setDeletingId(record.id)
    try {
      await deleteApp(record.id)
      message.success(`应用「${record.name}」已永久删除`)
      setSelectedKeys((keys) => keys.filter((key) => key !== record.id))
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    } finally {
      setDeletingId(null)
    }
  }

  const openEditModal = (record: Application) => {
    setEditTarget(record)
    // Modal 还未打开时 Form 未挂载，用 requestAnimationFrame 等渲染后再 setFieldsValue
    requestAnimationFrame(() => {
      editForm.setFieldsValue({
        name: record.name,
        description: record.description ?? '',
        visibility_template: record.visibility_template ?? 'all',
        visibility_lock: record.visibility_lock ?? false,
        admin_scope_mode: record.admin_scope_mode ?? 'all_admin',
      })
    })
  }

  const handleEditSave = async () => {
    if (!editTarget) return
    try {
      const values = await editForm.validateFields()
      setEditSaving(true)
      await updateApp(editTarget.id, {
        name: values.name.trim(),
        description: values.description?.trim() ?? '',
        visibility_template: values.visibility_template,
        visibility_lock: values.visibility_lock,
        admin_scope_mode: values.admin_scope_mode,
      })
      message.success('应用信息已更新')
      setEditTarget(null)
      void load()
    } catch (error) {
      if (error && (error as { errorFields?: unknown }).errorFields) return
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setEditSaving(false)
    }
  }

  const handleCopy = async (record: Application) => {
    setCopyingId(record.id)
    try {
      const result = await copyApp(record.id)
      message.success(`已复制为「${result.name}」`)
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '复制失败')
    } finally {
      setCopyingId(null)
    }
  }

  const showBatchFailures = (failed: AppBatchDeleteItem[]) => {
    modal.error({
      title: `${failed.length} 个应用删除失败`,
      content: (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {failed.map((item) => (
            <li key={item.application_id}>
              {item.name ?? item.application_id}：{item.error ?? '未知错误'}
            </li>
          ))}
        </ul>
      ),
      okText: '知道了',
    })
  }

  const handleBatchDelete = () => {
    const targets = filtered.filter((item) => selectedKeys.includes(item.id))
    if (targets.length === 0) return
    modal.confirm({
      title: `确认永久删除选中的 ${targets.length} 个应用？`,
      content: DELETE_SCOPE_DESC,
      okText: '永久删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        setBatchBusy(true)
        try {
          const result = await batchDeleteApps(targets.map((item) => item.id))
          if (result.failed === 0) {
            message.success(`已永久删除 ${result.succeeded} 个应用`)
          } else {
            message.warning(`成功 ${result.succeeded} 个，失败 ${result.failed} 个`)
            showBatchFailures(result.items.filter((item) => !item.success))
          }
          setSelectedKeys([])
          void load()
        } catch (error) {
          message.error(error instanceof Error ? error.message : '批量删除失败')
        } finally {
          setBatchBusy(false)
        }
      },
    })
  }

  if (loading) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <Spin />
      </div>
    )
  }

  return (
    <div className="page-card">
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Typography.Title level={4} style={{ margin: 0 }}>
            产品级应用
          </Typography.Title>
          <Typography.Text type="secondary">平台统一发布，租户通过应用市场自助开通</Typography.Text>
        </Col>
        <Col>
          <Space>
            {canDelete && selectedKeys.length > 0 && (
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={batchBusy}
                onClick={handleBatchDelete}
              >
                批量删除（{selectedKeys.length}）
              </Button>
            )}
            <Button type="primary" onClick={() => setCreateOpen(true)}>
              新建应用
            </Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col>
          <Segmented
            value={typeFilter}
            onChange={(value) => {
              setTypeFilter(value as TypeFilter)
              setSelectedKeys([])
            }}
            options={[
              { label: '智能体', value: 'agent' },
              { label: '工作流', value: 'workflow' },
              { label: '对话流', value: 'chatflow' },
              { label: '全部', value: 'all' },
            ]}
          />
        </Col>
        <Col flex="auto">
          <Input
            placeholder="按名称过滤"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              setSelectedKeys([])
            }}
            allowClear
            style={{ width: 260 }}
          />
        </Col>
      </Row>

      {filtered.length === 0 ? (
        <Empty description="暂无应用，点击右上角「新建应用」开始" />
      ) : (
        <Table
          rowKey="id"
          dataSource={filtered}
          pagination={false}
          rowSelection={
            canDelete
              ? {
                  selectedRowKeys: selectedKeys,
                  onChange: (keys) => setSelectedKeys(keys as string[]),
                }
              : undefined
          }
          columns={[
            {
              title: '名称',
              dataIndex: 'name',
              render: (name: string, record) => (
                <a
                  onClick={() => navigate(editPathFor(record.id, record.flow_type))}
                  style={{ fontWeight: 500 }}
                >
                  {name}
                </a>
              ),
            },
            {
              title: '类型',
              dataIndex: 'flow_type',
              width: 110,
              render: (flowType: FlowType) => (
                <Tag color={FLOW_TYPE_TAG_COLORS[flowType] ?? 'blue'}>
                  {FLOW_TYPE_LABELS[flowType] ?? flowType}
                </Tag>
              ),
            },
            { title: '描述', dataIndex: 'description', ellipsis: true },
            {
              title: '市场',
              dataIndex: 'is_listed_in_market',
              render: (listed: boolean, record) => (
                <Switch
                  checked={listed}
                  checkedChildren="已上架"
                  unCheckedChildren="未上架"
                  onChange={(checked) =>
                    modal.confirm({
                      title: checked ? '确认上架到市场？' : '确认从市场下架？',
                      content: checked
                        ? '上架后租户可在市场浏览并自助开通。'
                        : '下架后新租户无法开通，已开通的租户实例保留。',
                      onOk: () => handleToggleListing(record, checked),
                    })
                  }
                />
              ),
            },
            {
              title: '状态',
              dataIndex: 'is_enabled',
              render: (enabled: boolean, record) => (
                <Switch
                  checked={enabled}
                  checkedChildren="启用"
                  unCheckedChildren="禁用"
                  onChange={(checked) => handleToggleEnabled(record, checked)}
                />
              ),
            },
            {
              title: '更新时间',
              dataIndex: 'updated_at',
              render: (v: string) => (v ? new Date(v).toLocaleString() : '-'),
            },
            {
              title: '操作',
              key: 'actions',
              width: 300,
              onCell: () => ({ style: { whiteSpace: 'nowrap' } }),
              render: (_, record) => (
                <Space size={4} style={{ whiteSpace: 'nowrap' }}>
                  <Button type="link" size="small" onClick={() => setDetailApp(record)}>
                    详情
                  </Button>
                  <Button
                    type="link"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openEditModal(record)}
                  >
                    编辑
                  </Button>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => navigate(`/apps/${record.id}/edit`)}
                  >
                    编辑画布
                  </Button>
                  <Button
                    type="link"
                    size="small"
                    icon={<CopyOutlined />}
                    loading={copyingId === record.id}
                    onClick={() =>
                      modal.confirm({
                        title: `确认复制应用「${record.name}」？`,
                        content:
                          '将复制应用名称、描述、画布、变量定义与可见范围；副本默认未启用、未上架、未发布。',
                        okText: '复制',
                        cancelText: '取消',
                        onOk: () => handleCopy(record),
                      })
                    }
                  >
                    复制
                  </Button>
                  {canDelete && (
                    <Popconfirm
                      title={`确认删除应用「${record.name}」？`}
                      description={DELETE_SCOPE_DESC}
                      okText="永久删除"
                      okButtonProps={{ danger: true, loading: deletingId === record.id }}
                      cancelText="取消"
                      onConfirm={() => handleDelete(record)}
                    >
                      <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                        删除
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ),
            },
          ]}
        />
      )}

      <Modal
        title="新建应用"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false)
          resetCreateForm()
        }}
        footer={null}
        width={560}
      >
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>应用类型</Typography.Text>
          <Row gutter={12} style={{ marginTop: 8 }}>
            {FLOW_TYPE_OPTIONS.map((opt) => {
              const selected = newFlowType === opt.value
              return (
                <Col span={12} key={opt.value}>
                  <Card
                    size="small"
                    hoverable
                    onClick={() => setNewFlowType(opt.value)}
                    style={{
                      borderColor: selected ? opt.color : undefined,
                      boxShadow: selected ? `0 0 0 1px ${opt.color}` : undefined,
                      cursor: 'pointer',
                      height: '100%',
                    }}
                  >
                    <div style={{ fontWeight: 600, color: selected ? opt.color : undefined }}>
                      {opt.label}
                    </div>
                    <div style={{ fontSize: 12, color: '#595959', marginTop: 4, minHeight: 36 }}>
                      {opt.desc}
                    </div>
                    <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 8 }}>
                      初始画布：{opt.nodes}
                    </div>
                    <div style={{ fontSize: 12, color: '#8c8c8c' }}>试运行：{opt.trial}</div>
                  </Card>
                </Col>
              )
            })}
          </Row>
        </div>
        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>
            应用名称 <Typography.Text type="danger">*</Typography.Text>
          </Typography.Text>
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="给应用起个名字，便于识别"
            maxLength={50}
            showCount
            style={{ marginTop: 8 }}
          />
        </div>
        <div style={{ marginBottom: 24 }}>
          <Typography.Text strong>应用描述</Typography.Text>
          <Input.TextArea
            value={newDesc}
            onChange={(e) => setNewDesc(e.target.value)}
            placeholder="简单描述应用的用途（选填）"
            rows={3}
            maxLength={200}
            showCount
            style={{ marginTop: 8 }}
          />
        </div>
        <Row justify="end" gutter={8}>
          <Col>
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
          </Col>
          <Col>
            <Button loading={creating} onClick={() => handleCreate(false)}>
              创建
            </Button>
          </Col>
          <Col>
            <Button type="primary" loading={creating} onClick={() => handleCreate(true)}>
              创建并进入编排
            </Button>
          </Col>
        </Row>
      </Modal>

      <Drawer
        open={!!detailApp}
        width={640}
        title={detailApp ? `应用详情：${detailApp.name}` : '应用详情'}
        onClose={() => setDetailApp(null)}
        destroyOnClose
      >
        {detailApp && (
          <Tabs
            defaultActiveKey="basic"
            items={[
              {
                key: 'basic',
                label: '基本信息',
                children: (
                  <Descriptions
                    column={1}
                    size="small"
                    items={[
                      { key: 'name', label: '名称', children: detailApp.name },
                      {
                        key: 'flow',
                        label: '类型',
                        children: FLOW_TYPE_LABELS[detailApp.flow_type] ?? detailApp.flow_type,
                      },
                      { key: 'desc', label: '描述', children: detailApp.description || '-' },
                      {
                        key: 'listing',
                        label: '市场状态',
                        children: detailApp.is_listed_in_market ? '已上架' : '未上架',
                      },
                      {
                        key: 'enabled',
                        label: '启用状态',
                        children: detailApp.is_enabled ? '启用' : '禁用',
                      },
                      {
                        key: 'updated',
                        label: '更新时间',
                        children: detailApp.updated_at
                          ? new Date(detailApp.updated_at).toLocaleString()
                          : '-',
                      },
                    ]}
                  />
                ),
              },
              {
                key: 'tenants',
                label: '已开通租户',
                children: <ObjectTenantsTab objectType="app" objectId={detailApp.id} />,
              },
            ]}
          />
        )}
      </Drawer>

      <Modal
        title={editTarget ? `编辑应用：${editTarget.name}` : '编辑应用'}
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={handleEditSave}
        confirmLoading={editSaving}
        okText="保存"
        cancelText="取消"
        destroyOnClose
        width={560}
      >
        <Form form={editForm} layout="vertical" preserve={false}>
          <Form.Item
            label="应用名称"
            name="name"
            rules={[
              { required: true, message: '请输入应用名称' },
              { max: 50, message: '名称不超过 50 个字符' },
            ]}
          >
            <Input placeholder="给应用起个名字" maxLength={50} showCount />
          </Form.Item>
          <Form.Item label="应用描述" name="description" rules={[{ max: 200 }]}>
            <Input.TextArea
              placeholder="简单描述应用的用途（选填）"
              rows={3}
              maxLength={200}
              showCount
            />
          </Form.Item>
          <Divider orientation="left" plain>
            高级设置
          </Divider>
          <Form.Item
            label="默认可见范围模板"
            name="visibility_template"
            tooltip="租户未配置可见范围时的兜底值：全员可见，或等待租户自行配置白名单"
          >
            <Radio.Group
              options={[
                { value: 'all', label: '全员可见' },
                { value: 'whitelist', label: '等待租户配置' },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="锁定可见范围"
            name="visibility_lock"
            valuePropName="checked"
            tooltip="锁定后租户管理端不可修改本租户的可见范围"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label="管理范围模式"
            name="admin_scope_mode"
            tooltip="决定租户侧哪些管理员可配置该应用（二期按管理单元收敛）"
          >
            <Select
              options={[
                { value: 'creator_only', label: '仅创建者' },
                { value: 'mgmt_unit', label: '按管理单元' },
                { value: 'all_admin', label: '全部租户管理员' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
