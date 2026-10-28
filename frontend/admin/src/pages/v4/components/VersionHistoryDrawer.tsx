import { App, Button, Drawer, Empty, Input, Space, Table, Tag, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import {
  getEffectiveConfig,
  listFieldVersions,
  pinField,
  unpinField,
  type V4FieldVersion,
} from '../../../api/v4'

interface Props {
  open: boolean
  applicationId: string
  onClose: () => void
}

/** 字段版本历史 + 租户 pin 管理抽屉 */
export function VersionHistoryDrawer({ open, applicationId, onClose }: Props) {
  const { message } = App.useApp()
  const [versions, setVersions] = useState<V4FieldVersion[]>([])
  const [loading, setLoading] = useState(false)
  const [tenantId, setTenantId] = useState<string>('')
  const [effective, setEffective] = useState<Record<string, { version: number; pinned: boolean }>>({})

  const load = async () => {
    if (!applicationId) return
    setLoading(true)
    try {
      const [rows, eff] = await Promise.all([
        listFieldVersions(applicationId),
        tenantId ? getEffectiveConfig(applicationId, tenantId) : Promise.resolve({}),
      ])
      setVersions(rows)
      setEffective(eff)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '加载版本历史失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      setTenantId('')
      setEffective({})
      load()
    }
  }, [open, applicationId])

  useEffect(() => {
    if (open && tenantId) {
      load()
    }
  }, [tenantId])

  // 按 field_path 分组
  const grouped = useMemo(() => {
    const map = new Map<string, V4FieldVersion[]>()
    for (const v of versions) {
      const arr = map.get(v.field_path) ?? []
      arr.push(v)
      map.set(v.field_path, arr)
    }
    return Array.from(map.entries()).map(([path, list]) => ({
      path,
      list: list.sort((a, b) => b.version - a.version),
    }))
  }, [versions])

  const handlePin = async (fieldPath: string, version: number) => {
    if (!tenantId) {
      message.warning('请先输入租户 ID 再执行 pin')
      return
    }
    try {
      await pinField(applicationId, { tenant_id: tenantId, field_path: fieldPath, version })
      message.success(`已 pin 到 v${version}`)
      load()
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'pin 失败')
    }
  }

  const handleUnpin = async (fieldPath: string) => {
    if (!tenantId) return
    try {
      await unpinField(applicationId, tenantId, fieldPath)
      message.success('已取消 pin')
      load()
    } catch (e) {
      message.error(e instanceof Error ? e.message : 'unpin 失败')
    }
  }

  return (
    <Drawer
      title="字段版本历史"
      width={720}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={load} loading={loading}>
            刷新
          </Button>
        </Space>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <Typography.Text type="secondary" style={{ marginRight: 8 }}>
          租户 ID（查看 pin 状态并执行 pin/unpin）：
        </Typography.Text>
        <Input
          placeholder="留空则不展示 pin 信息"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          style={{ width: 360 }}
          allowClear
        />
      </div>

      {grouped.length === 0 && !loading ? (
        <Empty description="尚无字段版本历史（保存 graph 后自动快照）" />
      ) : (
        grouped.map(({ path, list }) => {
          const effInfo = effective[path]
          return (
            <div key={path} style={{ marginBottom: 20 }}>
              <div
                style={{
                  fontFamily: 'monospace',
                  fontSize: 12,
                  background: '#f5f5f5',
                  padding: '6px 10px',
                  borderRadius: 4,
                  marginBottom: 8,
                }}
              >
                <Space>
                  <span>{path}</span>
                  {effInfo?.pinned && (
                    <Tag color="gold">租户已 pin v{effInfo.version}</Tag>
                  )}
                  {effInfo && !effInfo.pinned && <Tag color="default">跟随 latest</Tag>}
                </Space>
              </div>
              <Table
                size="small"
                rowKey={(r) => `${r.field_path}#${r.version}`}
                dataSource={list}
                loading={loading}
                pagination={false}
                columns={[
                  {
                    title: '版本',
                    dataIndex: 'version',
                    width: 70,
                    render: (v: number) => <strong>v{v}</strong>,
                  },
                  {
                    title: '值',
                    dataIndex: 'value',
                    render: (v: unknown) => (
                      <Typography.Text
                        code
                        style={{ fontSize: 11, wordBreak: 'break-all' }}
                        ellipsis={{ tooltip: JSON.stringify(v) }}
                      >
                        {JSON.stringify(v)}
                      </Typography.Text>
                    ),
                  },
                  {
                    title: '变更说明',
                    dataIndex: 'changelog',
                    width: 220,
                    render: (s: string) => (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {s}
                      </Typography.Text>
                    ),
                  },
                  {
                    title: '操作',
                    width: 140,
                    render: (_: unknown, record) => {
                      const isPinned = effInfo?.pinned && effInfo.version === record.version
                      return (
                        <Space size={4}>
                          {tenantId && (
                            <>
                              {isPinned ? (
                                <Button size="small" danger onClick={() => handleUnpin(path)}>
                                  取消 pin
                                </Button>
                              ) : (
                                <Button
                                  size="small"
                                  type="link"
                                  disabled={effInfo?.pinned === true}
                                  onClick={() => handlePin(path, record.version)}
                                >
                                  pin 到此版本
                                </Button>
                              )}
                            </>
                          )}
                        </Space>
                      )
                    },
                  },
                ]}
              />
            </div>
          )
        })
      )}
    </Drawer>
  )
}
