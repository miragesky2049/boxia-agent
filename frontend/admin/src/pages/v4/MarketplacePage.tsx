import { App, Avatar, Button, Card, Empty, List, Spin, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { listMarketplace, listMyApps, subscribeApplication } from '../../api/v4'

export default function V4MarketplacePage() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [marketplace, setMarketplace] = useState<
    Array<{ id: string; name: string; avatar_url: string | null; description: string }>
  >([])
  const [myApps, setMyApps] = useState<Set<string>>(new Set())
  const [subscribingId, setSubscribingId] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [items, mine] = await Promise.all([listMarketplace(), listMyApps()])
      setMarketplace(items)
      setMyApps(new Set(mine.map((m) => m.application_id)))
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载市场失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const handleSubscribe = async (applicationId: string, name: string) => {
    setSubscribingId(applicationId)
    try {
      await subscribeApplication(applicationId)
      message.success(`已开通「${name}」`)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '开通失败')
    } finally {
      setSubscribingId(null)
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
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        应用市场
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        浏览平台发布的应用，自助开通到本租户。
      </Typography.Paragraph>

      {marketplace.length === 0 ? (
        <Empty description="市场暂无应用" />
      ) : (
        <List
          grid={{ gutter: 16, column: 3 }}
          dataSource={marketplace}
          renderItem={(item) => {
            const subscribed = myApps.has(item.id)
            return (
              <List.Item>
                <Card
                  actions={[
                    subscribed ? (
                      <Tag color="green" key="subscribed" style={{ margin: 0 }}>
                        已开通
                      </Tag>
                    ) : (
                      <Button
                        key="subscribe"
                        type="link"
                        loading={subscribingId === item.id}
                        onClick={() => handleSubscribe(item.id, item.name)}
                      >
                        立即开通
                      </Button>
                    ),
                  ]}
                >
                  <Card.Meta
                    avatar={<Avatar src={item.avatar_url}>{item.name.slice(0, 1)}</Avatar>}
                    title={item.name}
                    description={item.description || '暂无描述'}
                  />
                </Card>
              </List.Item>
            )
          }}
        />
      )}
    </div>
  )
}
