import { MessageOutlined, RightOutlined } from '@ant-design/icons'
import { Alert, Card, Col, Empty, Input, Pagination, Row, Skeleton, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listAgents } from '../api/agents'
import type { UserAgentSummary } from '../api/types'
import AppHeader from '../components/AppHeader'

const PAGE_SIZE = 12

function formatDescription(value: string): string {
  const trimmed = value.trim()
  return trimmed || '暂无简介'
}

function AgentAvatar({ agent }: { agent: UserAgentSummary }) {
  if (agent.avatar_url) {
    return <img src={agent.avatar_url} alt="" className="agent-card__avatar" />
  }
  return (
    <span className="agent-card__avatar agent-card__avatar--fallback">
      {agent.name.slice(0, 1).toUpperCase()}
    </span>
  )
}

function AgentCard({ agent }: { agent: UserAgentSummary }) {
  return (
    <Col xs={24} sm={12} lg={8} xl={6}>
      <Link to={`/agents/${agent.id}/chat`} style={{ display: 'block', height: '100%' }}>
        <Card className="agent-card" styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column' } }}>
          <div className="agent-card__head">
            <AgentAvatar agent={agent} />
            <Typography.Title level={5} style={{ margin: 0 }}>
              {agent.name}
            </Typography.Title>
          </div>
          <Typography.Paragraph
            ellipsis={{ rows: 2 }}
            style={{ margin: 0, color: '#86909c', fontSize: 13 }}
          >
            {formatDescription(agent.description)}
          </Typography.Paragraph>
          <Typography.Text className="agent-card__link" style={{ color: '#2f6bff' }}>
            <MessageOutlined style={{ marginRight: 4, fontSize: 12 }} />
            发起对话 <RightOutlined style={{ fontSize: 11 }} />
          </Typography.Text>
        </Card>
      </Link>
    </Col>
  )
}

function AgentCardSkeleton() {
  return (
    <Col xs={24} sm={12} lg={8} xl={6}>
      <Card>
        <Skeleton active avatar={{ size: 40 }} paragraph={{ rows: 2 }} title={{ width: '40%' }} />
      </Card>
    </Col>
  )
}

export default function AgentListPage() {
  const [items, setItems] = useState<UserAgentSummary[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listAgents({ page, page_size: PAGE_SIZE, keyword: keyword || undefined })
      setItems(result.items)
      setTotal(result.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载智能体失败')
    } finally {
      setLoading(false)
    }
  }, [page, keyword])

  useEffect(() => {
    void load()
  }, [load])

  const handleSearch = (value: string) => {
    setPage(1)
    setKeyword(value.trim())
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div style={{ minHeight: '100svh', background: '#f7f8fc' }}>
      <AppHeader />
      <main style={{ width: 'min(1200px, 100%)', margin: '0 auto', padding: '24px 24px 56px' }}>
        <section className="hero-banner">
          <div>
            <h1>可用智能体</h1>
            <p>这里只展示你的角色被授权且已启用的智能体。</p>
          </div>
          <Input.Search
            size="large"
            placeholder="搜索智能体名称"
            allowClear
            style={{ width: 320 }}
            onSearch={handleSearch}
            onChange={(event) => setSearchInput(event.target.value)}
            value={searchInput}
            enterButton
          />
        </section>

        {error && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
            message={error}
            action={
              <button
                type="button"
                onClick={() => void load()}
                style={{
                  background: 'transparent',
                  border: '1px solid #d9d9d9',
                  borderRadius: 6,
                  padding: '4px 12px',
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                重试
              </button>
            }
          />
        )}

        {!error && loading ? (
          <Row gutter={[16, 16]}>
            {Array.from({ length: 8 }).map((_, index) => (
              <AgentCardSkeleton key={index} />
            ))}
          </Row>
        ) : !error && items.length === 0 ? (
          <Empty
            description={
              <span style={{ color: '#86909c' }}>
                {keyword ? '没有匹配的智能体' : '暂无可用的智能体'}
                <br />
                <small>如长时间为空，请联系租户管理员确认角色授权。</small>
              </span>
            }
            style={{ padding: '48px 0' }}
          />
        ) : (
          <Row gutter={[16, 16]}>
            {items.map((agent) => (
              <AgentCard key={agent.id} agent={agent} />
            ))}
          </Row>
        )}

        {!error && totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: 32 }}>
            <Pagination
              current={page}
              total={total}
              pageSize={PAGE_SIZE}
              onChange={(next) => {
                setPage(next)
              }}
              showSizeChanger={false}
            />
          </div>
        )}
      </main>
    </div>
  )
}
