import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Input, Menu, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useAuth } from '../../auth/AuthContext'
import { listApps, listResources } from '../../api/apps'
import type { ResourceType } from '../../api/apps'
import {
  applyBatch,
  listTenantEntitlements,
  previewBatch,
  type EntitlementItem,
  type EntitlementMode,
  type EntitlementObjectType,
  type EntitlementPreview,
  type EntitlementView,
} from '../../api/entitlements'
import { fetchPublicTenants } from '../../api/tenant'
import type { Tenant } from '../../api/types'
import BatchPreviewModal, { type BatchFormValues } from './BatchPreviewModal'
import EntitlementTable, {
  OBJECT_TYPE_LABELS,
  STATUS_LABELS,
  canRevoke,
  rowKeyOf,
} from './EntitlementTable'

const RECENT_STORAGE_KEY = 'boxia.entitlements.recentTenants'
const OBJECT_TYPES: EntitlementObjectType[] = ['app', 'tool', 'skill', 'prompt', 'knowledge']
const ALL_STATUSES = ['active', 'wait_effect', 'expired', 'revoked', 'suspended', 'disabled']

function readRecentTenantIds(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string') : []
  } catch {
    return []
  }
}

function writeRecentTenantId(tenantId: string): void {
  const next = [tenantId, ...readRecentTenantIds().filter((id) => id !== tenantId)].slice(0, 5)
  localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(next))
}

interface PickerRow {
  id: string
  name: string
  hint: string
}

export default function TenantEntitlementsPage() {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canManage = hasPermission('button:entitlement:manage')

  const [tenants, setTenants] = useState<Tenant[]>([])
  const [tenantId, setTenantId] = useState<string | undefined>(undefined)
  const [objectType, setObjectType] = useState<EntitlementObjectType | 'all'>('all')
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  const [rows, setRows] = useState<EntitlementView[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])

  const [preview, setPreview] = useState<EntitlementPreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [modalState, setModalState] = useState<{
    mode: EntitlementMode
    items: EntitlementItem[]
  } | null>(null)

  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerType, setPickerType] = useState<EntitlementObjectType>('app')
  const [pickerRows, setPickerRows] = useState<PickerRow[]>([])
  const [pickerSelected, setPickerSelected] = useState<string[]>([])
  const [pickerLoading, setPickerLoading] = useState(false)

  const recentIds = useMemo(() => readRecentTenantIds(), [tenantId])

  useEffect(() => {
    fetchPublicTenants()
      .then((items) => {
        setTenants(items)
        setTenantId((current) => {
          if (current) return current
          const recent = readRecentTenantIds().find((id) => items.some((t) => t.id === id))
          return recent ?? items.find((t) => t.is_active)?.id
        })
      })
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载租户失败'),
      )
  }, [message])

  const loadRows = useCallback(async () => {
    if (!tenantId) return
    setLoading(true)
    try {
      const result = await listTenantEntitlements(tenantId, {
        object_type: objectType === 'all' ? undefined : objectType,
        status: statusFilter,
        keyword: keyword || undefined,
        page,
        page_size: pageSize,
      })
      setRows(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载权益列表失败')
    } finally {
      setLoading(false)
    }
  }, [tenantId, objectType, statusFilter, keyword, page, pageSize, message])

  const loadCounts = useCallback(async () => {
    if (!tenantId) {
      setCounts({})
      return
    }
    try {
      const results = await Promise.all(
        OBJECT_TYPES.map((type) =>
          listTenantEntitlements(tenantId, {
            object_type: type,
            status: statusFilter,
            keyword: keyword || undefined,
            page: 1,
            page_size: 1,
          }),
        ),
      )
      const next: Record<string, number> = {}
      OBJECT_TYPES.forEach((type, index) => {
        next[type] = results[index]?.total ?? 0
      })
      next.all = OBJECT_TYPES.reduce((sum, type) => sum + (next[type] ?? 0), 0)
      setCounts(next)
    } catch {
      // 计数失败不阻塞列表
    }
  }, [tenantId, statusFilter, keyword])

  useEffect(() => {
    void loadRows()
  }, [loadRows])

  useEffect(() => {
    void loadCounts()
  }, [loadCounts])

  const handleTenantChange = (id: string) => {
    writeRecentTenantId(id)
    setTenantId(id)
    setPage(1)
    setSelectedKeys([])
  }

  const openPreview = useCallback(
    async (mode: EntitlementMode, items: EntitlementItem[]) => {
      if (!tenantId || items.length === 0) return
      setModalState({ mode, items })
      setPreview(null)
      setPreviewLoading(true)
      try {
        setPreview(await previewBatch({ tenant_id: tenantId, mode, items }))
      } catch (error) {
        message.error(error instanceof Error ? error.message : '预览失败')
        setModalState(null)
      } finally {
        setPreviewLoading(false)
      }
    },
    [tenantId, message],
  )

  const handleBatchRevoke = () => {
    const items = rows
      .filter((row) => selectedKeys.includes(rowKeyOf(row)) && canRevoke(row))
      .map((row) => ({
        object_type: row.object_type as EntitlementObjectType,
        object_id: row.object_id,
      }))
    void openPreview('revoke', items)
  }

  const handleConfirm = async (values: BatchFormValues) => {
    if (!modalState || !tenantId) return
    setSubmitting(true)
    try {
      const result = await applyBatch({
        tenant_id: tenantId,
        mode: modalState.mode,
        items: modalState.items,
        reason: values.reason || undefined,
        auth_type: values.auth_type,
        start_time: values.period?.[0]?.toISOString() ?? null,
        expire_time: values.period?.[1]?.toISOString() ?? null,
      })
      if (result.failed.length > 0) {
        message.error(
          `校验未通过，本次未写入：${result.failed.map((f) => `${f.reason}`).join('；')}`,
        )
      } else if (result.updated > 0) {
        const affected =
          result.affected_role_grants > 0 ? `，影响角色授权 ${result.affected_role_grants} 项` : ''
        message.success(`已更新 ${result.updated} 项${affected}`)
      }
      setModalState(null)
      setSelectedKeys([])
      void loadRows()
      void loadCounts()
    } catch (error) {
      // 严格模式 422（权益仍被角色授权引用）等整体拒绝走这里，弹窗保留便于修改参数
      message.error(error instanceof Error ? error.message : '操作失败')
    } finally {
      setSubmitting(false)
    }
  }

  useEffect(() => {
    if (!pickerOpen) return
    setPickerLoading(true)
    setPickerSelected([])
    const load =
      pickerType === 'app'
        ? listApps({ owner_type: 'platform' }).then((items) =>
            items.map((item): PickerRow => ({
              id: item.id,
              name: item.name,
              hint: item.is_enabled ? '' : '已停用',
            })),
          )
        : listResources({ type: pickerType as ResourceType, owner_type: 'platform' }).then(
            (items) =>
              items.map((item): PickerRow => ({
                id: item.id,
                name: item.name,
                hint: item.is_deprecated ? '已弃用' : item.is_enabled ? '' : '已停用',
              })),
          )
    load
      .then(setPickerRows)
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载可开通对象失败'),
      )
      .finally(() => setPickerLoading(false))
  }, [pickerOpen, pickerType, message])

  const pickerColumns: ColumnsType<PickerRow> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string, row) => (
        <Space size={4}>
          {name}
          {row.hint && <Tag color="default">{row.hint}</Tag>}
        </Space>
      ),
    },
  ]

  const tenantOptions = useMemo(() => {
    const label = (t: Tenant) => `${t.name}（${t.code}）`
    const recent = recentIds
      .map((id) => tenants.find((t) => t.id === id))
      .filter((t): t is Tenant => Boolean(t))
    const groups: { label: string; options: { value: string; label: string }[] }[] = []
    if (recent.length > 0) {
      groups.push({
        label: '最近访问',
        options: recent.map((t) => ({ value: t.id, label: label(t) })),
      })
    }
    groups.push({
      label: '全部租户',
      options: tenants
        .filter((t) => !recentIds.includes(t.id))
        .map((t) => ({ value: t.id, label: label(t) })),
    })
    return groups
  }, [tenants, recentIds])

  return (
    <div className="page-card">
      <Space style={{ marginBottom: 12 }} wrap>
        <Select
          style={{ width: 280 }}
          placeholder="选择租户"
          showSearch
          optionFilterProp="label"
          value={tenantId}
          options={tenantOptions}
          onChange={handleTenantChange}
        />
        <Select
          style={{ width: 140 }}
          placeholder="状态筛选"
          allowClear
          value={statusFilter}
          onChange={(value) => {
            setStatusFilter(value)
            setPage(1)
          }}
          options={ALL_STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] }))}
        />
        <Input.Search
          style={{ width: 220 }}
          placeholder="搜索名称"
          allowClear
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        {canManage && (
          <>
            <Button type="primary" disabled={!tenantId} onClick={() => setPickerOpen(true)}>
              批量开通
            </Button>
            <Button disabled={selectedKeys.length === 0} onClick={handleBatchRevoke}>
              批量取消（{selectedKeys.length}）
            </Button>
          </>
        )}
      </Space>
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <Menu
          mode="inline"
          style={{ width: 160, borderInlineEnd: '1px solid #f0f0f0' }}
          selectedKeys={[objectType]}
          onClick={({ key }) => {
            setObjectType(key as EntitlementObjectType | 'all')
            setPage(1)
            setSelectedKeys([])
          }}
          items={[
            { key: 'all', label: `全部${counts.all !== undefined ? `（${counts.all}）` : ''}` },
            ...OBJECT_TYPES.map((type) => ({
              key: type,
              label: `${OBJECT_TYPE_LABELS[type]}${counts[type] !== undefined ? `（${counts[type]}）` : ''}`,
            })),
          ]}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <EntitlementTable
            rows={rows}
            total={total}
            page={page}
            pageSize={pageSize}
            loading={loading}
            selectedKeys={selectedKeys}
            canManage={canManage}
            onPageChange={(p, ps) => {
              setPage(p)
              setPageSize(ps)
              setSelectedKeys([])
            }}
            onSelectChange={setSelectedKeys}
            onRevoke={(row) =>
              void openPreview('revoke', [
                { object_type: row.object_type as EntitlementObjectType, object_id: row.object_id },
              ])
            }
            onGrant={(row) =>
              void openPreview('grant', [
                { object_type: row.object_type as EntitlementObjectType, object_id: row.object_id },
              ])
            }
          />
        </div>
      </div>
      <Modal
        open={pickerOpen}
        title="选择要开通的对象"
        width={560}
        okText="下一步：预览"
        okButtonProps={{ disabled: pickerSelected.length === 0 || pickerLoading }}
        onOk={() => {
          setPickerOpen(false)
          void openPreview(
            'grant',
            pickerSelected.map((id) => ({ object_type: pickerType, object_id: id })),
          )
        }}
        onCancel={() => setPickerOpen(false)}
      >
        <Select
          style={{ width: 160, marginBottom: 12 }}
          value={pickerType}
          onChange={(value) => setPickerType(value)}
          options={OBJECT_TYPES.map((t) => ({ value: t, label: OBJECT_TYPE_LABELS[t] }))}
        />
        <Table<PickerRow>
          rowKey="id"
          size="small"
          loading={pickerLoading}
          columns={pickerColumns}
          dataSource={pickerRows}
          pagination={{ pageSize: 8, size: 'small' }}
          rowSelection={{
            selectedRowKeys: pickerSelected,
            onChange: (keys) => setPickerSelected(keys as string[]),
          }}
        />
      </Modal>
      <BatchPreviewModal
        open={modalState !== null}
        mode={modalState?.mode ?? 'grant'}
        preview={preview}
        loading={previewLoading}
        submitting={submitting}
        onCancel={() => setModalState(null)}
        onConfirm={(values) => void handleConfirm(values)}
      />
    </div>
  )
}
