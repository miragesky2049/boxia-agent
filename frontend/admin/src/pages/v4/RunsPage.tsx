import {
  ClockCircleOutlined,
  CloseCircleOutlined,
  CheckCircleOutlined,
  PauseCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  getRunDetail,
  listApplicationRuns,
  resumeRun,
  runApplication,
  type V4NodeExecution,
  type V4RunDetail,
  type V4RunItem,
} from '../../api/v4'

const STATUS_META: Record<
  V4RunItem['status'],
  { color: string; label: string; icon: React.ReactNode }
> = {
  running: { color: 'processing', label: '运行中', icon: <ClockCircleOutlined /> },
  success: { color: 'success', label: '成功', icon: <CheckCircleOutlined /> },
  error: { color: 'error', label: '失败', icon: <CloseCircleOutlined /> },
  interrupted: { color: 'warning', label: '待人审', icon: <PauseCircleOutlined /> },
}

function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">—</Typography.Text>
  }
  let text: string
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  } catch {
    text = String(value)
  }
  return (
    <pre
      style={{
        margin: 0,
        padding: 8,
        background: '#f5f5f5',
        borderRadius: 4,
        fontSize: 12,
        maxHeight: 240,
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}
    >
      {text}
    </pre>
  )
}

function NodeExecutionRow({ node }: { node: V4NodeExecution }) {
  const [expanded, setExpanded] = useState(false)
  const status = node.error ? 'error' : 'success'
  const duration = node.duration_ms != null ? `${node.duration_ms} ms` : '—'
  const tokens = node.token_usage?.total_tokens
  return (
    <div
      style={{
        borderLeft: `3px solid ${node.error ? '#ff4d4f' : '#52c41a'}`,
        padding: '8px 12px',
        marginBottom: 8,
        background: '#fafafa',
      }}
    >
      <Space size="middle" style={{ width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <Tag>{node.node_type}</Tag>
          <Typography.Text strong>{node.node_id}</Typography.Text>
          <Tag color={status === 'error' ? 'error' : 'success'}>{status}</Tag>
          <Typography.Text type="secondary">{duration}</Typography.Text>
          {tokens != null && (
            <Tag color="blue">tokens: {tokens}</Tag>
          )}
        </Space>
        <Button type="link" size="small" onClick={() => setExpanded((v) => !v)}>
          {expanded ? '收起' : '详情'}
        </Button>
      </Space>
      {expanded && (
        <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              输入：
            </Typography.Text>
            <JsonBlock value={node.input} />
          </div>
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              输出：
            </Typography.Text>
            <JsonBlock value={node.output} />
          </div>
          {node.error && (
            <div>
              <Typography.Text type="danger" style={{ fontSize: 12 }}>
                错误：
              </Typography.Text>
              <JsonBlock value={node.error} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function V4RunsPage() {
  const { appId } = useParams<{ appId: string }>()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<V4RunItem[]>([])
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detail, setDetail] = useState<V4RunDetail | null>(null)

  // 审批 Modal
  const [approveOpen, setApproveOpen] = useState(false)
  const [approvingRun, setApprovingRun] = useState<V4RunItem | null>(null)
  const [approveComment, setApproveComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [rerunningId, setRerunningId] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!appId) return
    setLoading(true)
    try {
      const rows = await listApplicationRuns(appId)
      setItems(rows)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载运行历史失败')
    } finally {
      setLoading(false)
    }
  }, [appId, message])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = async (runId: string) => {
    setDetailOpen(true)
    setDetailLoading(true)
    setDetail(null)
    try {
      const data = await getRunDetail(runId)
      setDetail(data)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载运行详情失败')
      setDetailOpen(false)
    } finally {
      setDetailLoading(false)
    }
  }

  const openApprove = (record: V4RunItem) => {
    setApprovingRun(record)
    setApproveComment('')
    setApproveOpen(true)
  }

  const submitApproval = async (approved: boolean) => {
    if (!approvingRun || !appId) return
    setSubmitting(true)
    try {
      await resumeRun(appId, approvingRun.langgraph_thread_id, {
        approved,
        comment: approveComment,
      })
      message.success(approved ? '已批准，流程继续' : '已拒绝')
      setApproveOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '审批提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRerun = async (record: V4RunItem) => {
    if (!appId) return
    setRerunningId(record.id)
    try {
      const result = await runApplication(appId, record.input ?? {})
      if (result.status === 'success') {
        message.success('重跑完成')
      } else {
        message.info('重跑已启动，等待人审')
      }
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '重跑失败')
    } finally {
      setRerunningId(null)
    }
  }

  const columns: ColumnsType<V4RunItem> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: V4RunItem['status']) => {
        const meta = STATUS_META[status] ?? STATUS_META.running
        return (
          <Tag icon={meta.icon} color={meta.color}>
            {meta.label}
          </Tag>
        )
      },
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '耗时',
      key: 'duration',
      width: 120,
      render: (_, record) => {
        if (!record.finished_at) return <Typography.Text type="secondary">—</Typography.Text>
        const ms = dayjs(record.finished_at).diff(dayjs(record.started_at))
        return `${(ms / 1000).toFixed(2)} s`
      },
    },
    {
      title: '输入摘要',
      dataIndex: 'input',
      ellipsis: true,
      render: (v: Record<string, unknown> | null) => {
        if (!v) return <Typography.Text type="secondary">—</Typography.Text>
        const keys = Object.keys(v)
        if (keys.length === 0) return <Typography.Text type="secondary">—</Typography.Text>
        return keys
          .slice(0, 3)
          .map((k) => `${k}=${String(v[k]).slice(0, 40)}`)
          .join(', ')
      },
    },
    {
      title: '错误',
      dataIndex: 'error',
      width: 200,
      ellipsis: true,
      render: (v: string | null) =>
        v ? (
          <Typography.Text type="danger">{v}</Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openDetail(record.id)}>
            详情
          </Button>
          <Button
            type="link"
            size="small"
            loading={rerunningId === record.id}
            onClick={() => handleRerun(record)}
          >
            重跑
          </Button>
          {record.status === 'interrupted' && (
            <Button type="link" size="small" onClick={() => openApprove(record)}>
              审批
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="page-card">
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          运行历史
        </Typography.Title>
        <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
          刷新
        </Button>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        查看该应用在本租户下的运行记录与节点执行轨迹。
      </Typography.Paragraph>

      {items.length === 0 && !loading ? (
        <Empty description="暂无运行记录" />
      ) : (
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{ pageSize: 10, size: 'small' }}
        />
      )}

      <Drawer
        open={detailOpen}
        width={720}
        title="运行详情"
        onClose={() => setDetailOpen(false)}
        loading={detailLoading}
      >
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="Run ID" span={2}>
                <Typography.Text code>{detail.run.id}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {(() => {
                  const meta = STATUS_META[detail.run.status] ?? STATUS_META.running
                  return (
                    <Tag icon={meta.icon} color={meta.color}>
                      {meta.label}
                    </Tag>
                  )
                })()}
              </Descriptions.Item>
              <Descriptions.Item label="Thread ID">
                <Typography.Text code>{detail.run.langgraph_thread_id}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {dayjs(detail.run.started_at).format('YYYY-MM-DD HH:mm:ss')}
              </Descriptions.Item>
              <Descriptions.Item label="完成时间">
                {detail.run.finished_at
                  ? dayjs(detail.run.finished_at).format('YYYY-MM-DD HH:mm:ss')
                  : '—'}
              </Descriptions.Item>
            </Descriptions>

            <div>
              <Typography.Text strong>输入</Typography.Text>
              <div style={{ marginTop: 4 }}>
                <JsonBlock value={detail.run.input} />
              </div>
            </div>
            <div>
              <Typography.Text strong>输出</Typography.Text>
              <div style={{ marginTop: 4 }}>
                <JsonBlock value={detail.run.output} />
              </div>
            </div>
            {detail.run.error && (
              <div>
                <Typography.Text strong type="danger">
                  错误
                </Typography.Text>
                <div style={{ marginTop: 4 }}>
                  <JsonBlock value={detail.run.error} />
                </div>
              </div>
            )}

            <div>
              <Typography.Text strong>节点执行轨迹（{detail.node_executions.length}）</Typography.Text>
              <div style={{ marginTop: 8 }}>
                {detail.node_executions.length === 0 ? (
                  <Empty description="无节点执行记录" />
                ) : (
                  detail.node_executions.map((node) => (
                    <NodeExecutionRow key={node.id} node={node} />
                  ))
                )}
              </div>
            </div>
          </Space>
        )}
      </Drawer>

      <Modal
        open={approveOpen}
        title="人审节点审批"
        onCancel={() => setApproveOpen(false)}
        footer={
          <Space>
            <Button onClick={() => setApproveOpen(false)}>取消</Button>
            <Button danger loading={submitting} onClick={() => submitApproval(false)}>
              拒绝
            </Button>
            <Button type="primary" loading={submitting} onClick={() => submitApproval(true)}>
              批准
            </Button>
          </Space>
        }
      >
        {approvingRun && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                运行快照：
              </Typography.Text>
              <div style={{ marginTop: 4 }}>
                <JsonBlock value={approvingRun.input} />
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                审批意见：
              </Typography.Text>
              <Input.TextArea
                rows={3}
                value={approveComment}
                onChange={(e) => setApproveComment(e.target.value)}
                placeholder="可填写审批备注（可选）"
              />
            </div>
          </Space>
        )}
      </Modal>
    </div>
  )
}
