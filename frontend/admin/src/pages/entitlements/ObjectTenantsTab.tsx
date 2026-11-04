import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listObjectTenants, type EntitlementTenantRow } from '../../api/entitlements'
import { STATUS_LABELS } from './EntitlementTable'

const AUTH_SOURCE_LABELS: Record<string, string> = {
  OPS: '运营开通',
  MARKET_APPLY: '市场申请',
}

interface Props {
  objectType: string
  objectId: string
}

const PAGE_SIZE = 20

/** 对象反查 Tab：展示持有该对象权益的租户，点击租户名跳转到该开通授权页（P2-5）。 */
export default function ObjectTenantsTab({ objectType, objectId }: Props) {
  const navigate = useNavigate()
  const [rows, setRows] = useState<EntitlementTenantRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(
    async (targetPage: number) => {
      setLoading(true)
      setError(null)
      try {
        const result = await listObjectTenants(objectType, objectId, {
          page: targetPage,
          page_size: PAGE_SIZE,
        })
        setRows(result.items)
        setTotal(result.total)
        setPage(targetPage)
      } catch (e) {
        setError(e instanceof Error ? e.message : '加载已开通租户失败')
      } finally {
        setLoading(false)
      }
    },
    [objectType, objectId],
  )

  useEffect(() => {
    void load(1)
  }, [load])

  const columns: ColumnsType<EntitlementTenantRow> = [
    {
      title: '租户',
      dataIndex: 'tenant_name',
      render: (name: string, row) => (
        <a onClick={() => navigate(`/entitlements?tenant=${row.tenant_id}`)}>
          {name || row.tenant_id.slice(0, 8)}
        </a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => <Tag>{STATUS_LABELS[status] ?? status}</Tag>,
    },
    {
      title: '来源',
      dataIndex: 'auth_source',
      width: 110,
      render: (source: string) => AUTH_SOURCE_LABELS[source] ?? source,
    },
    {
      title: '开通时间',
      dataIndex: 'granted_at',
      width: 160,
      render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-'),
    },
  ]

  return (
    <Table<EntitlementTenantRow>
      rowKey="tenant_id"
      size="small"
      loading={loading}
      columns={columns}
      dataSource={rows}
      locale={error ? { emptyText: error } : undefined}
      pagination={{
        current: page,
        pageSize: PAGE_SIZE,
        total,
        size: 'small',
        onChange: (p) => void load(p),
      }}
    />
  )
}
