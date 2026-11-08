import { ClearOutlined, FileSearchOutlined } from '@ant-design/icons'
import { App, Button, Drawer, Input, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { clearAuditLogs, listAuditLogs, type AuditLogItem } from '../api/audit'

export default function AuditLogsPage() {
  const { message, modal } = App.useApp()
  const [items, setItems] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [action, setAction] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<AuditLogItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listAuditLogs({
        page,
        page_size: pageSize,
        action: action || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载审计日志失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, action, message])

  const handleClear = () => {
    void (async () => {
      try {
        const result = await clearAuditLogs()
        message.success(`已清空 ${result.deleted} 条审计日志`)
        setPage(1)
        void load()
      } catch (error) {
        message.error(error instanceof Error ? error.message : '清空失败')
      }
    })()
  }

  useEffect(() => {
    void load()
  }, [load])

  const columns: ColumnsType<AuditLogItem> = [
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作人',
      dataIndex: 'actor_username',
      width: 140,
      render: (value: string | null, record) =>
        value ? (
          value
        ) : (
          <Typography.Text type="secondary">{record.actor_id || '系统'}</Typography.Text>
        ),
    },
    {
      title: '动作',
      dataIndex: 'action',
      width: 200,
      render: (value: string) => <Tag color="blue">{value}</Tag>,
    },
    {
      title: '资源',
      key: 'resource',
      render: (_, record) =>
        record.resource_type ? (
          <Typography.Text style={{ fontSize: 12 }}>
            {record.resource_type}
            {record.resource_id ? (
              <span style={{ color: '#999' }}> · {record.resource_id}</span>
            ) : null}
          </Typography.Text>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      width: 130,
      render: (value: string | null) =>
        value ?? <Typography.Text type="secondary">—</Typography.Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => setDetail(record)}>
          详情
        </Button>
      ),
    },
  ]

  return (
    <div className="page-card">
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <FileSearchOutlined style={{ fontSize: 22, color: '#1677ff' }} />
          <Typography.Title level={4} style={{ margin: 0 }}>
            审计日志
          </Typography.Title>
        </Space>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        平台级操作审计：登录、权限变更、应用发布、配置修改等关键动作留痕。
      </Typography.Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Input
          placeholder="按 action 过滤，如 auth.login"
          allowClear
          value={action}
          onChange={(e) => {
            setPage(1)
            setAction(e.target.value)
          }}
          style={{ width: 280 }}
        />
        <Button type="primary" onClick={() => void load()} loading={loading}>
          查询
        </Button>
        <Button
          danger
          icon={<ClearOutlined />}
          onClick={() =>
            modal.confirm({
              title: '确认清空全部审计日志？',
              content: '清空后不可恢复，建议先导出备份。',
              okText: '确认清空',
              okButtonProps: { danger: true },
              cancelText: '取消',
              onOk: handleClear,
            })
          }
        >
          清空日志
        </Button>
      </Space>

      <Table<AuditLogItem>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => {
            setPage(p)
            setPageSize(ps)
          },
        }}
      />

      <Drawer
        open={detail !== null}
        onClose={() => setDetail(null)}
        width={560}
        title="审计日志详情"
      >
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                时间
              </Typography.Text>
              <div>{dayjs(detail.created_at).format('YYYY-MM-DD HH:mm:ss')}</div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                操作人
              </Typography.Text>
              <div>
                {detail.actor_username ?? '系统'}
                {detail.actor_id && (
                  <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    {detail.actor_id}
                  </Typography.Text>
                )}
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                动作
              </Typography.Text>
              <div>
                <Tag color="blue">{detail.action}</Tag>
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                资源
              </Typography.Text>
              <div>
                {detail.resource_type ?? '—'}
                {detail.resource_id ? ` · ${detail.resource_id}` : ''}
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                IP / UA
              </Typography.Text>
              <div style={{ fontSize: 12 }}>
                {detail.ip ?? '—'}
                {detail.user_agent ? (
                  <div style={{ color: '#999', wordBreak: 'break-all' }}>{detail.user_agent}</div>
                ) : null}
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                request_id
              </Typography.Text>
              <div style={{ fontSize: 12, fontFamily: 'monospace' }}>
                {detail.request_id ?? '—'}
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                明细
              </Typography.Text>
              <pre
                style={{
                  margin: '4px 0 0',
                  padding: 8,
                  background: '#f5f5f5',
                  borderRadius: 4,
                  fontSize: 12,
                  maxHeight: 420,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                }}
              >
                {JSON.stringify(detail.detail, null, 2)}
              </pre>
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}
