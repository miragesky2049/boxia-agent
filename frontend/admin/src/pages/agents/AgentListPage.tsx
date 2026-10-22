import { PlusOutlined, RobotOutlined } from '@ant-design/icons'
import { App, Avatar, Button, Input, Popconfirm, Select, Space, Switch, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { deleteAgent, listAgents, updateAgent, getAgent } from '../../api/agents'
import type { AgentSummary } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { useTenant } from '../../tenant/TenantContext'

export default function AgentListPage() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { canWrite } = useAuth()
  const { isPlatform } = useTenant()
  const [items, setItems] = useState<AgentSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [enabledFilter, setEnabledFilter] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listAgents({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        is_enabled: enabledFilter === undefined ? undefined : enabledFilter === 'true',
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, enabledFilter, message])

  useEffect(() => {
    void load()
  }, [load])

  const handleDelete = async (id: number) => {
    try {
      await deleteAgent(id)
      message.success('已删除')
      if (items.length === 1 && page > 1) {
        setPage(page - 1)
      } else {
        await load()
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleToggle = async (record: AgentSummary, enabled: boolean) => {
    try {
      const detail = await getAgent(record.id)
      await updateAgent(record.id, {
        name: detail.name,
        avatar_url: detail.avatar_url,
        description: detail.description,
        is_enabled: enabled,
        config: detail.config,
        tool_ids: detail.tool_ids,
        skill_ids: detail.skill_ids,
      })
      message.success(enabled ? '已启用' : '已停用')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const columns: ColumnsType<AgentSummary> = [
    {
      title: '智能体',
      dataIndex: 'name',
      key: 'name',
      render: (_: unknown, record: AgentSummary) => (
        <div className="agent-cell">
          <Avatar
            size={38}
            src={record.avatar_url || undefined}
            icon={<RobotOutlined />}
            style={{ backgroundColor: '#eef3ff', color: '#2f6bff' }}
          />
          <div>
            <div className="resource-name">
              {record.name}
              {record.is_platform ? (
                <Tag color="geekblue" bordered={false} style={{ marginLeft: 8 }}>
                  平台级
                </Tag>
              ) : (
                !isPlatform && (
                  <Tag color="green" bordered={false} style={{ marginLeft: 8 }}>
                    本租户
                  </Tag>
                )
              )}
            </div>
            <div className="resource-desc">{record.description || '暂无描述'}</div>
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 130,
      render: (enabled: boolean, record: AgentSummary) => (
        <Switch
          size="small"
          checked={enabled}
          checkedChildren="启用"
          unCheckedChildren="停用"
          disabled={!canWrite || (!isPlatform && record.is_platform)}
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
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: AgentSummary) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => navigate(`/agents/${record.id}/edit`)}>
            配置
          </Button>
          {canWrite && (isPlatform || !record.is_platform) && (
            <Popconfirm
              title="确认删除该智能体？"
              description="删除后关联配置将一并移除。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDelete(record.id)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
          {canWrite && !isPlatform && record.is_platform && <Tag bordered={false}>只读</Tag>}
        </Space>
      ),
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">智能体管理</h2>
          <p className="page-header__desc">
            创建并配置智能体，设置模型、提示词、渠道与可用工具技能。
          </p>
        </div>
        {canWrite && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/agents/new')}>
            新建智能体
          </Button>
        )}
      </div>

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索智能体名称或描述"
          style={{ width: 280 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 130 }}
          value={enabledFilter}
          options={[
            { label: '启用', value: 'true' },
            { label: '停用', value: 'false' },
          ]}
          onChange={(value) => {
            setEnabledFilter(value)
            setPage(1)
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {total} 个智能体
        </Tag>
      </div>

      <Table<AgentSummary>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
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
          },
        }}
      />
    </div>
  )
}
