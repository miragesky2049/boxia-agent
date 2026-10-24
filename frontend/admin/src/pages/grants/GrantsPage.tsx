import { SafetyCertificateOutlined } from '@ant-design/icons'
import { App, Button, Input, Select, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { grantsApi } from '../../api/access'
import type { GrantOverviewItem, GrantState, ResourceType } from '../../api/types'
import AuthorizationDrawer from '../../components/AuthorizationDrawer'
import { useTenant } from '../../tenant/TenantContext'
import BatchGrantModal from './BatchGrantModal'

const RESOURCE_TABS: { key: ResourceType; label: string }[] = [
  { key: 'agent', label: '智能体' },
  { key: 'skill', label: '技能' },
  { key: 'tool', label: '工具' },
  { key: 'component', label: '组件' },
  { key: 'prompt', label: '提示词' },
]

const RESOURCE_LABELS: Record<ResourceType, string> = {
  agent: '智能体',
  skill: '技能',
  tool: '工具',
  component: '组件',
  prompt: '提示词',
}

const MAX_BATCH_SELECTION = 100

export default function GrantsPage() {
  const { message } = App.useApp()
  const { isPlatform } = useTenant()
  const [resourceType, setResourceType] = useState<ResourceType>('agent')
  const [items, setItems] = useState<GrantOverviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [grantState, setGrantState] = useState<GrantState | undefined>(undefined)
  const [selectedRowKeys, setSelectedRowKeys] = useState<number[]>([])
  const [loading, setLoading] = useState(false)
  const [drawerTarget, setDrawerTarget] = useState<GrantOverviewItem | null>(null)
  const [batchOpen, setBatchOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await grantsApi.overview(resourceType, {
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        grant_state: grantState,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权列表失败')
    } finally {
      setLoading(false)
    }
  }, [resourceType, page, pageSize, keyword, grantState, message])

  useEffect(() => {
    void load()
  }, [load])

  const resetSelection = () => setSelectedRowKeys([])

  const scopeText = (record: GrantOverviewItem) => {
    if (isPlatform) {
      return record.grant_count === 0
        ? '未直接授权'
        : `已授权 ${record.tenant_count} 个租户 · ${record.grant_count} 条授权`
    }
    return record.is_default_visible
      ? '默认：本租户全部角色可见'
      : `已限定 ${record.role_count} 个角色`
  }

  const columns: ColumnsType<GrantOverviewItem> = [
    {
      title: '名称',
      key: 'name',
      render: (_: unknown, record: GrantOverviewItem) => (
        <div>
          <div className="resource-name">
            {record.name}
            {record.is_platform ? (
              <Tag color="geekblue" bordered={false} style={{ marginLeft: 8 }}>
                平台级
              </Tag>
            ) : (
              <Tag color="green" bordered={false} style={{ marginLeft: 8 }}>
                本租户
              </Tag>
            )}
          </div>
          {record.description && <div className="resource-desc">{record.description}</div>}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 90,
      render: (enabled: boolean) => (enabled ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '授权范围',
      key: 'scope',
      width: 260,
      render: (_: unknown, record: GrantOverviewItem) => scopeText(record),
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
      width: 110,
      render: (_: unknown, record: GrantOverviewItem) => (
        <Button type="link" size="small" onClick={() => setDrawerTarget(record)}>
          配置授权
        </Button>
      ),
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">授权管理</h2>
          <p className="page-header__desc">
            集中配置智能体、技能、工具、组件与提示词的访问授权，无需逐个进入资源页面。
          </p>
        </div>
      </div>

      <Tabs
        activeKey={resourceType}
        items={RESOURCE_TABS.map((tab) => ({ key: tab.key, label: tab.label }))}
        onChange={(key) => {
          setResourceType(key as ResourceType)
          setPage(1)
          setKeyword('')
          setGrantState(undefined)
          resetSelection()
        }}
      />

      <div className="page-toolbar">
        <Input.Search
          key={resourceType}
          allowClear
          placeholder="搜索名称或描述"
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
            resetSelection()
          }}
        />
        <Select
          allowClear
          placeholder="全部授权状态"
          style={{ width: 150 }}
          value={grantState}
          options={[
            { label: '已授权', value: 'granted' },
            { label: '未配置', value: 'ungranted' },
          ]}
          onChange={(value) => {
            setGrantState(value)
            setPage(1)
            resetSelection()
          }}
        />
        <Button
          type="primary"
          icon={<SafetyCertificateOutlined />}
          disabled={selectedRowKeys.length === 0}
          onClick={() => setBatchOpen(true)}
        >
          批量授权
        </Button>
        <Tag color="blue" bordered={false}>
          共 {total} 个{RESOURCE_LABELS[resourceType]}
        </Tag>
        {selectedRowKeys.length > 0 && (
          <Tag color="orange" bordered={false}>
            已选 {selectedRowKeys.length} 个
          </Tag>
        )}
      </div>

      <Table<GrantOverviewItem>
        rowKey="resource_id"
        columns={columns}
        dataSource={items}
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          preserveSelectedRowKeys: true,
          onChange: (keys) => {
            if (keys.length > MAX_BATCH_SELECTION) {
              message.warning(`单次最多选择 ${MAX_BATCH_SELECTION} 个资源`)
              return
            }
            setSelectedRowKeys(keys.map(Number))
          },
        }}
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

      {drawerTarget && (
        <AuthorizationDrawer
          open={drawerTarget !== null}
          onClose={() => setDrawerTarget(null)}
          onSaved={() => void load()}
          resourceType={resourceType}
          resourceId={drawerTarget.resource_id}
          resourceName={drawerTarget.name}
        />
      )}

      <BatchGrantModal
        open={batchOpen}
        resourceType={resourceType}
        resourceIds={selectedRowKeys}
        onClose={() => setBatchOpen(false)}
        onSuccess={() => {
          resetSelection()
          void load()
        }}
      />
    </div>
  )
}
