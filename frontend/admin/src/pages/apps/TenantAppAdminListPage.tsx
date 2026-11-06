import { SettingOutlined } from '@ant-design/icons'
import { App, Button, Empty, Spin, Table, Tabs, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSubscribedApps, type SubscribedApp } from '../../api/tenantApps'

const ADMIN_SCOPE_MODE_LABELS: Record<string, string> = {
  all_admin: '全部管理员可管理',
  mgmt_unit: '按管理单元',
  creator_only: '仅创建者',
}

function VisibilityTag({ record }: { record: SubscribedApp }) {
  if (!record.configured) {
    return (
      <Tag color={record.visibility_template === 'all' ? 'green' : 'default'}>
        {record.visibility_template === 'all' ? '全员可见（默认）' : '未配置（不可见）'}
      </Tag>
    )
  }
  if (record.visibility === 'all') {
    return <Tag color="green">全员可见</Tag>
  }
  return <Tag color="blue">白名单 {record.whitelist_count} 条</Tag>
}

export default function TenantAppAdminListPage() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [apps, setApps] = useState<SubscribedApp[]>([])
  const [managedLoading, setManagedLoading] = useState(false)
  const [managed, setManaged] = useState<SubscribedApp[] | null>(null)

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        setApps(await listSubscribedApps())
      } catch (error) {
        message.error(error instanceof Error ? error.message : '加载已订阅应用失败')
      } finally {
        setLoading(false)
      }
    })()
  }, [message])

  const loadManaged = async () => {
    if (managed !== null || managedLoading) return
    setManagedLoading(true)
    try {
      setManaged(await listSubscribedApps('managed'))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载我管理的应用失败')
    } finally {
      setManagedLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <Spin />
      </div>
    )
  }

  const renderTable = (data: SubscribedApp[], showMode: boolean) => (
    <Table<SubscribedApp>
      rowKey="id"
      dataSource={data}
      pagination={false}
      columns={[
        {
          title: '应用名称',
          dataIndex: 'name',
          render: (_, record) => (
            <div>
              <Typography.Text strong>{record.name}</Typography.Text>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {record.description || '暂无描述'}
                </Typography.Text>
              </div>
            </div>
          ),
        },
        {
          title: '当前可见范围',
          key: 'visibility',
          width: 220,
          render: (_, record) => <VisibilityTag record={record} />,
        },
        {
          title: '平台锁定',
          dataIndex: 'visibility_lock',
          width: 100,
          render: (locked: boolean) =>
            locked ? <Tag color="orange">已锁定</Tag> : <Typography.Text>-</Typography.Text>,
        },
        ...(showMode
          ? [
              {
                title: '管理范围模式',
                dataIndex: 'admin_scope_mode',
                width: 150,
                render: (mode: string) => (
                  <Tag bordered={false}>{ADMIN_SCOPE_MODE_LABELS[mode] ?? mode}</Tag>
                ),
              },
            ]
          : []),
        {
          title: '操作',
          key: 'actions',
          width: 160,
          render: (_, record) => (
            <Button
              size="small"
              icon={<SettingOutlined />}
              onClick={() => navigate(`/tenant-apps/${record.id}`)}
            >
              配置可见范围
            </Button>
          ),
        },
      ]}
    />
  )

  return (
    <div className="page-card">
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        应用管理
      </Typography.Title>
      <Tabs
        onChange={(key) => {
          if (key === 'managed') void loadManaged()
        }}
        items={[
          {
            key: 'subscribed',
            label: '已订阅的产品级应用',
            children:
              apps.length === 0 ? (
                <Empty description="当前租户暂无生效中的产品级应用，请先到应用市场开通" />
              ) : (
                renderTable(apps, false)
              ),
          },
          {
            key: 'managed',
            label: '我管理的应用',
            children:
              managed === null ? (
                <div style={{ textAlign: 'center', padding: 32 }}>
                  <Spin spinning={managedLoading} />
                </div>
              ) : managed.length === 0 ? (
                <Empty description="当前没有由你管理的应用" />
              ) : (
                renderTable(managed, true)
              ),
          },
        ]}
      />
    </div>
  )
}
