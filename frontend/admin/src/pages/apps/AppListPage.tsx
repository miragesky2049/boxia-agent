import { App, Button, Col, Empty, Input, Modal, Row, Select, Spin, Switch, Table, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createApp,
  listApps,
  setAppEnabled,
  setAppListing,
  type Application,
} from '../../api/apps'

type AppTemplate = 'workflow' | 'chatbot' | 'agent'

const TEMPLATE_OPTIONS: Array<{
  value: AppTemplate
  label: string
  desc: string
}> = [
  { value: 'workflow', label: '工作流应用', desc: '多节点编排，适合固定流程自动化' },
  { value: 'chatbot', label: '对话应用', desc: '单轮/多轮对话，适合客服与问答' },
  { value: 'agent', label: '智能体', desc: '自主规划工具调用，适合复杂任务' },
]

export default function AppListPage() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<Application[]>([])
  const [keyword, setKeyword] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)

  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newTemplate, setNewTemplate] = useState<AppTemplate>('workflow')

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
    if (!keyword.trim()) return data
    return data.filter((item) => item.name.toLowerCase().includes(keyword.trim().toLowerCase()))
  }, [data, keyword])

  const resetCreateForm = () => {
    setNewName('')
    setNewDesc('')
    setNewTemplate('workflow')
  }

  const handleCreate = async (enterCanvas: boolean) => {
    if (!newName.trim()) {
      message.warning('请输入应用名称')
      return
    }
    setCreating(true)
    try {
      const result = await createApp({ name: newName.trim(), description: newDesc.trim() })
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

      <Input
        placeholder="按名称过滤"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        allowClear
        style={{ width: 260, marginBottom: 16 }}
      />

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
          <Select
            value={newTemplate}
            onChange={(value) => setNewTemplate(value)}
            style={{ width: '100%', marginTop: 8 }}
            options={TEMPLATE_OPTIONS.map((opt) => ({ value: opt.value, label: opt.label }))}
            optionRender={(option) => {
              const opt = TEMPLATE_OPTIONS.find((item) => item.value === option.value)
              return (
                <div>
                  <div>{opt?.label}</div>
                  <div style={{ fontSize: 12, color: '#8c8c8c' }}>{opt?.desc}</div>
                </div>
              )
            }}
          />
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
