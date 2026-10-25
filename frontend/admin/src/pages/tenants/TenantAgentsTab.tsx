import { CheckCircleOutlined, RobotOutlined, StopOutlined } from '@ant-design/icons'
import { App, Avatar, Button, Input, Popconfirm, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import {
  listTenantAgents,
  setTenantAgentOpened,
  setTenantAgentsOpened,
} from '../../api/tenant'
import type { TenantAgent } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'

interface TenantAgentsTabProps {
  tenantId: string
  onChanged?: () => void
}

export default function TenantAgentsTab({ tenantId, onChanged }: TenantAgentsTabProps) {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canUpdate = hasPermission('button:tenant:update')
  const [items, setItems] = useState<TenantAgent[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [openedOnly, setOpenedOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [batchAction, setBatchAction] = useState<'open' | 'close' | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listTenantAgents(tenantId, {
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        opened_only: openedOnly || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [tenantId, page, pageSize, keyword, openedOnly, message])

  useEffect(() => {
    void load()
  }, [load])

  const handleToggle = async (record: TenantAgent, opened: boolean) => {
    setPendingId(record.id)
    try {
      await setTenantAgentOpened(tenantId, record.id, opened)
      message.success(opened ? '已开通该智能体' : '已关闭该智能体，租户内角色授权已清理')
      await load()
      onChanged?.()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    } finally {
      setPendingId(null)
    }
  }

  const handleBatch = async (opened: boolean) => {
    if (selectedIds.length === 0) return
    setBatchAction(opened ? 'open' : 'close')
    try {
      const result = await setTenantAgentsOpened(tenantId, selectedIds, opened)
      message.success(
        opened
          ? `已批量开通 ${result.count} 个智能体`
          : `已批量关闭 ${result.count} 个智能体，租户内相关角色授权已清理`,
      )
      setSelectedIds([])
      await load()
      onChanged?.()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量操作失败')
    } finally {
      setBatchAction(null)
    }
  }

  const columns: ColumnsType<TenantAgent> = [
    {
      title: '智能体',
      key: 'agent',
      render: (_: unknown, record: TenantAgent) => (
        <div className="agent-cell">
          <Avatar
            size={38}
            src={record.avatar_url || undefined}
            icon={<RobotOutlined />}
            style={{ backgroundColor: '#eef3ff', color: '#2f6bff' }}
          />
          <div>
            <div className="resource-name">{record.name}</div>
            <div className="resource-desc">{record.description || '暂无描述'}</div>
          </div>
        </div>
      ),
    },
    {
      title: '智能体状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 120,
      render: (enabled: boolean) => (
        <Tag color={enabled ? 'green' : 'default'} bordered={false}>
          {enabled ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '开通状态',
      dataIndex: 'is_opened',
      key: 'is_opened',
      width: 120,
      render: (opened: boolean) => (
        <Tag color={opened ? 'blue' : 'default'} bordered={false}>
          {opened ? '已开通' : '未开通'}
        </Tag>
      ),
    },
    {
      title: '开通时间',
      dataIndex: 'opened_at',
      key: 'opened_at',
      width: 170,
      render: (value: string | null) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'),
    },
    ...(canUpdate
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 100,
            render: (_: unknown, record: TenantAgent) =>
              record.is_opened ? (
                <Popconfirm
                  title="确认关闭该智能体？"
                  description="关闭后该租户内所有角色将失去访问权限，角色授权会一并清理。"
                  okText="关闭"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleToggle(record, false)}
                >
                  <Button type="link" size="small" danger loading={pendingId === record.id}>
                    关闭
                  </Button>
                </Popconfirm>
              ) : (
                <Button
                  type="link"
                  size="small"
                  loading={pendingId === record.id}
                  onClick={() => handleToggle(record, true)}
                >
                  开通
                </Button>
              ),
          },
        ]
      : []),
  ]

  return (
    <div>
      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索智能体名称或描述"
          style={{ width: 280 }}
          onSearch={(value) => {
            setSelectedIds([])
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Select
          style={{ width: 150 }}
          value={openedOnly ? 'opened' : 'all'}
          options={[
            { label: '全部智能体', value: 'all' },
            { label: '仅已开通', value: 'opened' },
          ]}
          onChange={(value) => {
            setSelectedIds([])
            setOpenedOnly(value === 'opened')
            setPage(1)
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {total} 个智能体
        </Tag>
        {canUpdate && (
          <>
            <div className="page-toolbar__spacer" />
            <span className="page-toolbar__hint">已选 {selectedIds.length} 项</span>
            <Space size={8}>
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                disabled={selectedIds.length === 0}
                loading={batchAction === 'open'}
                onClick={() => void handleBatch(true)}
              >
                批量开通
              </Button>
              <Popconfirm
                title={`确认关闭选中的 ${selectedIds.length} 个智能体？`}
                description="关闭后该租户内所有角色将失去访问权限，角色授权会一并清理。"
                okText="批量关闭"
                cancelText="取消"
                okButtonProps={{ danger: true }}
                disabled={selectedIds.length === 0}
                onConfirm={() => handleBatch(false)}
              >
                <Button
                  danger
                  icon={<StopOutlined />}
                  disabled={selectedIds.length === 0}
                  loading={batchAction === 'close'}
                >
                  批量关闭
                </Button>
              </Popconfirm>
            </Space>
          </>
        )}
      </div>

      <Table<TenantAgent>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        rowSelection={
          canUpdate
            ? {
                selectedRowKeys: selectedIds,
                onChange: (keys) => setSelectedIds(keys as string[]),
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
            setSelectedIds([])
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
      />
    </div>
  )
}
