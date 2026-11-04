import { AppstoreOutlined, ArrowRightOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Button, Card, Col, Empty, Row, Spin, Tag, Typography, App as AntApp } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listMyApps, type MyApp } from '../../api/apps'

export default function TenantAppsPage() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [loading, setLoading] = useState(true)
  const [apps, setApps] = useState<MyApp[]>([])

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        const items = await listMyApps()
        setApps(items)
      } catch (error) {
        message.error(error instanceof Error ? error.message : '加载已开通应用失败')
      } finally {
        setLoading(false)
      }
    })()
  }, [message])

  if (loading) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <Spin />
      </div>
    )
  }

  return (
    <div className="page-card">
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Typography.Title level={4} style={{ margin: 0 }}>
            我的应用
          </Typography.Title>
          <Typography.Text type="secondary">
            产品级为当前租户开通的应用，点击卡片即可使用
          </Typography.Text>
        </Col>
        <Col>
          <Button type="primary" onClick={() => navigate('/marketplace')}>
            去应用市场开通 <ArrowRightOutlined />
          </Button>
        </Col>
      </Row>

      {apps.length === 0 ? (
        <Empty description="暂无可使用的应用，请先到应用市场开通">
          <Button type="primary" onClick={() => navigate('/marketplace')}>
            浏览应用市场
          </Button>
        </Empty>
      ) : (
        <Row gutter={[16, 16]}>
          {apps.map((app) => (
            <Col key={app.application_id} xs={24} sm={12} md={8} lg={6}>
              <Card
                hoverable
                onClick={() => navigate(`/marketplace/apps/${app.application_id}/run`)}
                styles={{ body: { minHeight: 140 } }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
                  <div
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: 8,
                      background: '#f0f5ff',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 20,
                      color: '#1677ff',
                    }}
                  >
                    <AppstoreOutlined />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Typography.Text strong ellipsis>
                      {app.name}
                    </Typography.Text>
                  </div>
                </div>
                <Typography.Paragraph
                  type="secondary"
                  ellipsis={{ rows: 2 }}
                  style={{ fontSize: 13, minHeight: 40 }}
                >
                  {app.description || '暂无描述'}
                </Typography.Paragraph>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Tag color={app.status === 'active' ? 'green' : 'orange'}>
                    {app.status === 'active' ? '已开通' : app.status}
                  </Tag>
                  <PlayCircleOutlined style={{ color: '#1677ff' }} />
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
