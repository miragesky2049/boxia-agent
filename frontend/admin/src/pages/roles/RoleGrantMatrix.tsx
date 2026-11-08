import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Input,
  Menu,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { rolesApi } from '../../api/access'
import type { ResourceType, RoleGrantResource } from '../../api/types'

// 0073：原「角色授权」页（/role-access）的资源矩阵并入角色详情，四类资源 + 批量 + 全员可见
const GRANT_TYPES: { key: ResourceType; label: string }[] = [
  { key: 'tool', label: '工具' },
  { key: 'skill', label: '技能' },
  { key: 'prompt', label: '提示词' },
  { key: 'knowledge', label: '知识库' },
]

interface RoleGrantMatrixProps {
  roleId: string
  canManage: boolean
  isPlatformRole: boolean
}

export default function RoleGrantMatrix({
  roleId,
  canManage,
  isPlatformRole,
}: RoleGrantMatrixProps) {
  const { message } = App.useApp()
  const [resourceType, setResourceType] = useState<ResourceType>('tool')
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [grantedOnly, setGrantedOnly] = useState(false)
  const [rows, setRows] = useState<RoleGrantResource[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [batchBusy, setBatchBusy] = useState(false)
  const [pendingIds, setPendingIds] = useState<string[]>([])

  const loadCounts = useCallback(async () => {
    if (!roleId) return
    try {
      const summary = await rolesApi.grantSummary(roleId)
      setCounts(summary.counts)
    } catch {
      // 计数失败不阻塞列表
    }
  }, [roleId])

  const loadRows = useCallback(async () => {
    if (!roleId) return
    setLoading(true)
    try {
      const result = await rolesApi.listGrants(roleId, {
        resource_type: resourceType,
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        granted_only: grantedOnly,
      })
      setRows(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权候选失败')
    } finally {
      setLoading(false)
    }
  }, [roleId, resourceType, page, pageSize, keyword, grantedOnly, message])

  useEffect(() => {
    void loadRows()
  }, [loadRows])

  useEffect(() => {
    void loadCounts()
  }, [loadCounts])

  const refreshAfterWrite = () => {
    setSelectedKeys([])
    void loadRows()
    void loadCounts()
  }

  const selectedRows = rows.filter((row) => selectedKeys.includes(row.resource_id))
  const grantTargets = selectedRows.filter((row) => !row.is_granted)
  const revokeTargets = selectedRows.filter((row) => row.is_granted)

  const markPending = (resourceId: string, on: boolean) => {
    setPendingIds((prev) =>
      on ? [...prev, resourceId] : prev.filter((item) => item !== resourceId),
    )
  }

  const handleGrant = async (resourceIds: string[], tipSingle: string) => {
    setBatchBusy(true)
    try {
      const result = await rolesApi.addGrants(roleId, resourceType, resourceIds)
      if (result.updated < resourceIds.length) {
        message.info(`已授权 ${result.updated} 项，其余已为全员可见或既有授权`)
      } else if (tipSingle) {
        message.success(tipSingle)
      } else {
        message.success(`已授权 ${result.updated} 项`)
      }
      refreshAfterWrite()
    } catch (error) {
      // 未开通/未审核等拦截整体失败：候选集本就不含这类资源，兜底提示
      message.error(error instanceof Error ? error.message : '批量授权失败')
    } finally {
      setBatchBusy(false)
    }
  }

  const handleBatchRevoke = async () => {
    setBatchBusy(true)
    try {
      for (const row of revokeTargets) {
        await rolesApi.removeGrant(roleId, resourceType, row.resource_id)
      }
      message.success(`已取消授权 ${revokeTargets.length} 项`)
      refreshAfterWrite()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量取消失败')
      refreshAfterWrite()
    } finally {
      setBatchBusy(false)
    }
  }

  const handleRevokeOne = async (row: RoleGrantResource) => {
    markPending(row.resource_id, true)
    try {
      await rolesApi.removeGrant(roleId, resourceType, row.resource_id)
      message.success('已取消授权')
      refreshAfterWrite()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '取消授权失败')
    } finally {
      markPending(row.resource_id, false)
    }
  }

  const handleSetTenantWide = async (row: RoleGrantResource) => {
    markPending(row.resource_id, true)
    try {
      await rolesApi.setTenantWide(roleId, resourceType, row.resource_id)
      message.success('已设为全员可见')
      refreshAfterWrite()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '设置全员可见失败')
    } finally {
      markPending(row.resource_id, false)
    }
  }

  const handleUnsetTenantWide = async (row: RoleGrantResource) => {
    markPending(row.resource_id, true)
    try {
      // 取消全员可见复用单资源移除：后端把 tenant 档降级为其余角色的显式授权
      await rolesApi.removeGrant(roleId, resourceType, row.resource_id)
      message.success('已取消全员可见，其余角色保留显式授权')
      refreshAfterWrite()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '取消全员可见失败')
    } finally {
      markPending(row.resource_id, false)
    }
  }

  const columns: ColumnsType<RoleGrantResource> = [
    {
      title: '名称',
      key: 'name',
      render: (_: unknown, row) => (
        <div>
          <Space size={4}>
            <span style={row.is_enabled ? undefined : { color: 'rgba(0, 0, 0, 0.45)' }}>
              {row.name}
            </span>
            {row.is_platform && (
              <Tag color="geekblue" bordered={false}>
                平台级
              </Tag>
            )}
            {!row.is_enabled && (
              <Tooltip title="资源已停用：授权会保留，但运行时不可用">
                <Tag>已停用</Tag>
              </Tooltip>
            )}
            {row.is_tenant_wide && <Tag color="blue">全员可见</Tag>}
          </Space>
          {row.description && <div className="resource-desc">{row.description}</div>}
        </div>
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 150,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '授权',
      key: 'granted',
      width: 80,
      align: 'center',
      render: (_: unknown, row) => (
        <Tag color={row.is_granted ? 'success' : 'default'}>
          {row.is_granted ? '已授权' : '未授权'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_: unknown, row) => {
        if (!canManage) return null
        if (row.is_tenant_wide) {
          return (
            <Popconfirm
              title="取消全员可见"
              description="将降级为按角色授权，仅保留其余角色"
              okText="确认"
              cancelText="返回"
              onConfirm={() => void handleUnsetTenantWide(row)}
            >
              <Button
                type="link"
                size="small"
                danger
                loading={pendingIds.includes(row.resource_id)}
              >
                取消全员可见
              </Button>
            </Popconfirm>
          )
        }
        if (row.is_granted) {
          return (
            <Space size={4}>
              {!isPlatformRole && (
                <Button
                  type="link"
                  size="small"
                  loading={pendingIds.includes(row.resource_id)}
                  onClick={() => void handleSetTenantWide(row)}
                >
                  设为全员可见
                </Button>
              )}
              <Button
                type="link"
                size="small"
                danger
                loading={pendingIds.includes(row.resource_id)}
                onClick={() => void handleRevokeOne(row)}
              >
                取消授权
              </Button>
            </Space>
          )
        }
        return (
          <Button
            type="link"
            size="small"
            loading={pendingIds.includes(row.resource_id)}
            onClick={() => void handleGrant([row.resource_id], '已授权')}
          >
            授权
          </Button>
        )
      },
    },
  ]

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={
          isPlatformRole
            ? '候选为平台资源目录中可授权的启用资源；已弃用的资源不可新授权。'
            : '候选仅包含已开通给本租户且通过审核的资源；未开通或未审核的资源不会出现在这里，置灰行为已停用的资源。'
        }
      />
      <Space style={{ marginBottom: 12 }} wrap>
        <Menu
          mode="horizontal"
          style={{ minWidth: 480, borderBottom: 'none' }}
          selectedKeys={[resourceType]}
          onClick={({ key }) => {
            setResourceType(key as ResourceType)
            setPage(1)
            setSelectedKeys([])
          }}
          items={GRANT_TYPES.map((type) => ({
            key: type.key,
            label: `${type.label}${counts[type.key] !== undefined ? `（${counts[type.key]}）` : ''}`,
          }))}
        />
      </Space>
      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索名称或描述"
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Space size={8}>
          <Switch
            size="small"
            checked={grantedOnly}
            onChange={(checked) => {
              setGrantedOnly(checked)
              setPage(1)
            }}
          />
          <span>仅看已授权</span>
        </Space>
        <Tag color="blue" bordered={false}>
          共 {total} 个
        </Tag>
        {canManage && (
          <Space size={8}>
            <Button
              type="primary"
              disabled={grantTargets.length === 0}
              loading={batchBusy}
              onClick={() =>
                void handleGrant(
                  grantTargets.map((row) => row.resource_id),
                  '',
                )
              }
            >
              批量授权（{grantTargets.length}）
            </Button>
            <Button
              disabled={revokeTargets.length === 0}
              loading={batchBusy}
              onClick={() => void handleBatchRevoke()}
            >
              批量取消（{revokeTargets.length}）
            </Button>
          </Space>
        )}
      </div>
      <Table<RoleGrantResource>
        rowKey="resource_id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={rows}
        rowSelection={{
          selectedRowKeys: selectedKeys,
          onChange: (keys) => setSelectedKeys(keys as string[]),
          // 全员可见行不参与批量：取消必须走行内 Popconfirm 的降级确认
          getCheckboxProps: (row) => ({ disabled: !canManage || row.is_tenant_wide }),
        }}
        pagination={{
          current: page,
          pageSize,
          total,
          size: 'small',
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (count) => `共 ${count} 条`,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
            setSelectedKeys([])
          },
        }}
      />
    </div>
  )
}
