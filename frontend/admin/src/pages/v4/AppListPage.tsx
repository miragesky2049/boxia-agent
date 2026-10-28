import { App, Button, Col, Empty, Input, Row, Spin, Switch, Table, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createApp,
  listApps,
  setAppEnabled,
  setAppListing,
  type V4Application,
} from '../../api/v4'

export default function V4AppListPage() {
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<V4Application[]>([])
  const [keyword, setKeyword] = useState('')
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const items = await listApps({ owner_type: 'platform' })
      setData(items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载应用列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const filtered = useMemo(() => {
    if (!keyword.trim()) return data
    return data.filter((item) => item.name.toLowerCase().includes(keyword.trim().toLowerCase()))
  }, [data, keyword])

  const handleCreate = async () => {
    if (!newName.trim()) {
      message.warning('请输入应用名称')
      return
    }
    setCreating(true)
    try {
      const result = await createApp({ name: newName.trim() })
      message.success('应用已创建')
      setNewName('')
      navigate(`/v4/apps/${result.application_id}/edit`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleToggleListing = async (record: V4Application, listed: boolean) => {
    try {
      await setAppListing(record.id, listed)
      message.success(listed ? '已上架到市场' : '已下架')
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleToggleEnabled = async (record: V4Application, enabled: boolean) => {
    try {
      await setAppEnabled(record.id, enabled)
      message.success(enabled ? '已启用' : '已禁用')
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  if (loading) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <Spin />
      </div>
    )
  }

  return (
    <div className="page-card">
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Typography.Title level={4} style={{ margin: 0 }}>
            产品级应用
          </Typography.Title>
          <Typography.Text type="secondary">
            平台统一发布，租户通过应用市场自助开通
          </Typography.Text>
        </Col>
        <Col>
          <Input
            placeholder="搜索应用名称"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            style={{ width: 220, marginRight: 8 }}
            onPressEnter={handleCreate}
          />
          <Button type="primary" loading={creating} onClick={handleCreate}>
            新建应用
          </Button>
        </Col>
      </Row>

      <Input
        placeholder="按名称过滤"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        allowClear
        style={{ width: 260, marginBottom: 16 }}
      />

      {filtered.length === 0 ? (
        <Empty description="暂无应用，点击右上角「新建应用」开始" />
      ) : (
        <Table
          rowKey="id"
          dataSource={filtered}
          pagination={false}
          columns={[
            {
              title: '名称',
              dataIndex: 'name',
              render: (name: string, record) => (
                <a
                  onClick={() => navigate(`/v4/apps/${record.id}/edit`)}
                  style={{ fontWeight: 500 }}
                >
                  {name}
                </a>
              ),
            },
            { title: '描述', dataIndex: 'description', ellipsis: true },
            {
              title: '市场',
              dataIndex: 'is_listed_in_market',
              render: (listed: boolean, record) => (
                <Switch
                  checked={listed}
                  checkedChildren="已上架"
                  unCheckedChildren="未上架"
                  onChange={(checked) =>
                    modal.confirm({
                      title: checked ? '确认上架到市场？' : '确认从市场下架？',
                      content: checked
                        ? '上架后租户可在市场浏览并自助开通。'
                        : '下架后新租户无法开通，已开通的租户实例保留。',
                      onOk: () => handleToggleListing(record, checked),
                    })
                  }
                />
              ),
            },
            {
              title: '状态',
              dataIndex: 'is_enabled',
              render: (enabled: boolean, record) => (
                <Switch
                  checked={enabled}
                  checkedChildren="启用"
                  unCheckedChildren="禁用"
                  onChange={(checked) => handleToggleEnabled(record, checked)}
                />
              ),
            },
            {
              title: '更新时间',
              dataIndex: 'updated_at',
              render: (v: string) => new Date(v).toLocaleString(),
            },
            {
              title: '操作',
              render: (_, record) => (
                <Button type="link" size="small" onClick={() => navigate(`/v4/apps/${record.id}/edit`)}>
                  编辑画布
                </Button>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}
