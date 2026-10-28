import { App, Input, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { listAgentTenants } from '../../api/agents'
import type { AgentOpenedTenant } from '../../api/types'
import { useTenant } from '../../tenant/TenantContext'

export default function AgentTenantsTab({ agentId }: { agentId: string }) {
  const { message } = App.useApp()
  const { context } = useTenant()
  const [items, setItems] = useState<AgentOpenedTenant[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listAgentTenants(agentId, {
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
  }, [agentId, page, pageSize, keyword, message])

  useEffect(() => {
    void load()
  }, [load])

  const columns: ColumnsType<AgentOpenedTenant> = [
    {
      title: '租户',
      key: 'tenant',
      render: (_: unknown, record: AgentOpenedTenant) => (
        <div>
          <div className="resource-name">{record.name}</div>
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
      width: 110,
      render: (active: boolean) => (
        <Tag color={active ? 'green' : 'default'} bordered={false}>
          {active ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '开通时间',
      dataIndex: 'opened_at',
      key: 'opened_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
  ]

  return (
    <div>
      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索租户名称或编码"
          style={{ width: 280 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {total} 个租户已开通
        </Tag>
      </div>
      <Table<AgentOpenedTenant>
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
