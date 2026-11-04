import { Button, Space, Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { EntitlementObjectType, EntitlementView } from '../../api/entitlements'

export const OBJECT_TYPE_OPTIONS: { value: EntitlementObjectType | 'all'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'app', label: '应用' },
  { value: 'tool', label: '工具' },
  { value: 'skill', label: '技能' },
  { value: 'prompt', label: '提示词' },
  { value: 'knowledge', label: '知识库' },
]

export const OBJECT_TYPE_LABELS: Record<EntitlementObjectType, string> = {
  app: '应用',
  tool: '工具',
  skill: '技能',
  prompt: '提示词',
  knowledge: '知识库',
}

export const STATUS_LABELS: Record<string, string> = {
  active: '生效中',
  wait_effect: '待生效',
  expired: '已过期',
  suspended: '已暂停',
  disabled: '已禁用',
  revoked: '已取消',
}

const STATUS_COLORS: Record<string, string> = {
  active: 'success',
  wait_effect: 'processing',
  expired: 'warning',
  suspended: 'gold',
  disabled: 'gold',
  revoked: 'error',
}

/** 可取消的权益：终态（revoked/suspended/disabled）不展示取消入口，恢复走开通。 */
export function rowKeyOf(row: EntitlementView): string {
  return `${row.object_type}:${row.object_id}`
}

export function canRevoke(row: EntitlementView): boolean {
  return row.status !== 'revoked' && row.status !== 'suspended' && row.status !== 'disabled'
}

function formatRange(row: EntitlementView): string {
  const start = row.start_time ? dayjs(row.start_time).format('YYYY-MM-DD HH:mm') : '立即'
  const end = row.expire_time ? dayjs(row.expire_time).format('YYYY-MM-DD HH:mm') : '长期'
  return `${start} ~ ${end}`
}

interface EntitlementTableProps {
  rows: EntitlementView[]
  total: number
  page: number
  pageSize: number
  loading: boolean
  selectedKeys: string[]
  canManage: boolean
  onPageChange: (page: number, pageSize: number) => void
  onSelectChange: (keys: string[]) => void
  onRevoke: (row: EntitlementView) => void
  onGrant: (row: EntitlementView) => void
}

export default function EntitlementTable({
  rows,
  total,
  page,
  pageSize,
  loading,
  selectedKeys,
  canManage,
  onPageChange,
  onSelectChange,
  onRevoke,
  onGrant,
}: EntitlementTableProps) {
  const columns: ColumnsType<EntitlementView> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string, row) => (
        <Space size={4}>
          <span>{name || '(未命名)'}</span>
          {row.is_deprecated && <Tag color="default">已弃用</Tag>}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'object_type',
      width: 90,
      render: (type: string) => OBJECT_TYPE_LABELS[type as EntitlementObjectType] ?? type,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => (
        <Tag color={STATUS_COLORS[status] ?? 'default'}>{STATUS_LABELS[status] ?? status}</Tag>
      ),
    },
    { title: '有效期', key: 'range', width: 220, render: (_, row) => formatRange(row) },
    {
      title: '来源',
      key: 'source',
      width: 130,
      render: (_, row) => (
        <Tooltip title={`授权类型：${row.auth_type}`}>
          <Tag>{row.auth_source === 'OPS' ? '运营开通' : row.auth_source}</Tag>
        </Tooltip>
      ),
    },
    { title: '备注', dataIndex: 'remark', ellipsis: true },
    {
      title: '操作',
      key: 'actions',
      width: 110,
      render: (_, row) =>
        canManage &&
        (canRevoke(row) ? (
          <Button type="link" size="small" danger onClick={() => onRevoke(row)}>
            取消开通
          </Button>
        ) : (
          <Button type="link" size="small" onClick={() => onGrant(row)}>
            恢复开通
          </Button>
        )),
    },
  ]

  return (
    <Table<EntitlementView>
      rowKey={rowKeyOf}
      size="small"
      loading={loading}
      columns={columns}
      dataSource={rows}
      rowSelection={{
        selectedRowKeys: selectedKeys,
        onChange: (keys) => onSelectChange(keys as string[]),
        getCheckboxProps: (row) => ({ disabled: !canRevoke(row) && !canManage }),
      }}
      pagination={{
        current: page,
        pageSize,
        total,
        size: 'small',
        showSizeChanger: true,
        showTotal: (t) => `共 ${t} 条`,
        onChange: onPageChange,
      }}
    />
  )
}
