import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Modal,
  Row,
  Segmented,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createApp,
  listApps,
  setAppEnabled,
  setAppListing,
  type Application,
  type FlowType,
} from '../../api/apps'

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

export default function AppListPage() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<Application[]>([])
  const [keyword, setKeyword] = useState('')
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)

  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newFlowType, setNewFlowType] = useState<FlowType>('workflow')

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
    setNewFlowType('workflow')
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
        navigate(`/apps/${result.application_id}/edit`)
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
          <Typography.Text type="secondary">
            平台统一发布，租户通过应用市场自助开通
          </Typography.Text>
        </Col>
        <Col>
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            新建应用
          </Button>
        </Col>
      </Row>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col>
          <Segmented
            value={typeFilter}
            onChange={(value) => setTypeFilter(value as TypeFilter)}
            options={[
              { label: '全部', value: 'all' },
              { label: '工作流', value: 'workflow' },
              { label: '对话流', value: 'chatflow' },
            ]}
          />
        </Col>
        <Col flex="auto">
          <Input
            placeholder="按名称过滤"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
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
          columns={[
            {
              title: '名称',
              dataIndex: 'name',
              render: (name: string, record) => (
                <a
                  onClick={() => navigate(`/apps/${record.id}/edit`)}
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
                <Tag color={flowType === 'chatflow' ? 'purple' : 'blue'}>
                  {flowType === 'chatflow' ? '对话流' : '工作流'}
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
              render: (_, record) => (
                <Button type="link" size="small" onClick={() => navigate(`/apps/${record.id}/edit`)}>
                  编辑画布
                </Button>
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
                    <div style={{ fontSize: 12, color: '#8c8c8c' }}>
                      试运行：{opt.trial}
                    </div>
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
    </div>
  )
}
