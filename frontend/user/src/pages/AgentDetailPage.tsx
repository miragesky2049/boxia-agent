import { ArrowLeftOutlined, MessageOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Empty, Row, Skeleton, Tabs, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAgent } from '../api/agents'
import type { UserAgentDetail, UserPrompt, UserSkill, UserTool } from '../api/types'
import AppHeader from '../components/AppHeader'

interface ResourceLike {
  id: string
  name: string
  description: string
}

function ResourceCard<T extends ResourceLike>({
  item,
  extra,
  content,
}: {
  item: T
  extra?: React.ReactNode
  content?: string
}) {
  return (
    <Col xs={24} sm={12} lg={8}>
      <Card size="small" style={{ height: '100%' }}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          {item.name}
        </Typography.Title>
        <Typography.Paragraph
          ellipsis={{ rows: 2 }}
          style={{ color: '#86909c', fontSize: 13, marginBottom: extra ? 8 : 0 }}
        >
          {item.description.trim() || '暂无描述'}
        </Typography.Paragraph>
        {extra}
        {content && content.trim() && (
          <pre
            style={{
              maxHeight: 200,
              overflow: 'auto',
              margin: '8px 0 0',
              padding: 12,
              borderRadius: 8,
              background: '#f5f7fa',
              fontFamily: 'ui-monospace, Consolas, monospace',
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {content}
          </pre>
        )}
      </Card>
    </Col>
  )
}

function buildTabs(agent: UserAgentDetail) {
  const tabs: { key: string; label: string; count: number; node: React.ReactNode }[] = []

  if (agent.skills.length > 0) {
    tabs.push({
      key: 'skills',
      label: `技能 ${agent.skills.length}`,
      count: agent.skills.length,
      node: (
        <Row gutter={[12, 12]}>
          {agent.skills.map((item: UserSkill) => (
            <ResourceCard key={item.id} item={item} content={item.content} />
          ))}
        </Row>
      ),
    })
  }

  if (agent.tools.length > 0) {
    tabs.push({
      key: 'tools',
      label: `工具 ${agent.tools.length}`,
      count: agent.tools.length,
      node: (
        <Row gutter={[12, 12]}>
          {agent.tools.map((item: UserTool) => (
            <ResourceCard
              key={item.id}
              item={item}
              extra={<Tag color="blue">{item.type || '未指定类型'}</Tag>}
            />
          ))}
        </Row>
      ),
    })
  }

  if (agent.components.length > 0) {
    tabs.push({
      key: 'components',
      label: `组件 ${agent.components.length}`,
      count: agent.components.length,
      node: (
        <Row gutter={[12, 12]}>
          {agent.components.map((item: UserTool) => (
            <ResourceCard
              key={item.id}
              item={item}
              extra={<Tag color="geekblue">{item.type || '交互组件'}</Tag>}
            />
          ))}
        </Row>
      ),
    })
  }

  if (agent.prompts.length > 0) {
    tabs.push({
      key: 'prompts',
      label: `提示词 ${agent.prompts.length}`,
      count: agent.prompts.length,
      node: (
        <Row gutter={[12, 12]}>
          {agent.prompts.map((item: UserPrompt) => (
            <ResourceCard
              key={item.id}
              item={item}
              content={item.content}
              extra={
                <div>
                  <Tag color="purple">{item.category || '未分类'}</Tag>
                  {item.variables.length > 0 && (
                    <span style={{ fontSize: 12, color: '#86909c' }}>
                      变量：{item.variables.join('、')}
                    </span>
                  )}
                </div>
              }
            />
          ))}
        </Row>
      ),
    })
  }

  return tabs
}

function DetailAvatar({ agent }: { agent: UserAgentDetail }) {
  if (agent.avatar_url) {
    return <img src={agent.avatar_url} alt="" className="detail-avatar" />
  }
  return (
    <span className="detail-avatar detail-avatar--fallback">
      {agent.name.slice(0, 1).toUpperCase()}
    </span>
  )
}

export default function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>()
  const [agent, setAgent] = useState<UserAgentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    if (!agentId) {
      setError('智能体地址不正确')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    getAgent(agentId)
      .then((data) => {
        if (active) setAgent(data)
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : '加载智能体详情失败')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [agentId])

  const resourceTotal = agent
    ? agent.skills.length + agent.tools.length + agent.components.length + agent.prompts.length
    : 0

  const tabs = agent ? buildTabs(agent) : []

  return (
    <div style={{ minHeight: '100svh', background: '#f7f8fc' }}>
      <AppHeader />
      <main className="detail-content" style={{ width: 'min(1100px, 100%)', margin: '0 auto', padding: '24px 24px 56px' }}>
        <Link to="/">
          <Button type="link" icon={<ArrowLeftOutlined />} style={{ paddingLeft: 0 }}>
            返回智能体列表
          </Button>
        </Link>

        {loading ? (
          <Card>
            <Skeleton active avatar={{ size: 64 }} paragraph={{ rows: 4 }} title={{ width: '30%' }} />
          </Card>
        ) : error || !agent ? (
          <Alert type="error" showIcon message={error ?? '智能体不存在或未授权'} />
        ) : (
          <>
            <section className="detail-header-card">
              <DetailAvatar agent={agent} />
              <div style={{ flex: 1 }}>
                <Typography.Title level={3} style={{ margin: '0 0 6px' }}>
                  {agent.name}
                </Typography.Title>
                <Typography.Paragraph style={{ margin: '0 0 12px', color: '#86909c' }}>
                  {agent.description.trim() || '暂无简介'}
                </Typography.Paragraph>
                <Tag color={resourceTotal > 0 ? 'blue' : 'default'}>
                  {resourceTotal > 0 ? `${resourceTotal} 项可用资源` : '暂未配置资源'}
                </Tag>
              </div>
              <Link to={`/agents/${agent.id}/${agent.flow_type === 'workflow' ? 'workflow' : 'chat'}`}>
                <Button
                  type="primary"
                  size="large"
                  icon={agent.flow_type === 'workflow' ? <PlayCircleOutlined /> : <MessageOutlined />}
                >
                  {agent.flow_type === 'workflow' ? '开始运行' : '发起对话'}
                </Button>
              </Link>
            </section>

            {resourceTotal === 0 ? (
              <Empty
                description={
                  <span style={{ color: '#86909c' }}>
                    该智能体暂未配置对你可见的技能、工具、组件或提示词。
                    <br />
                    <small>如需使用，请联系租户管理员补充角色授权。</small>
                  </span>
                }
                style={{ padding: '48px 0' }}
              />
            ) : (
              <Tabs
                items={tabs.map((tab) => ({ key: tab.key, label: tab.label, children: tab.node }))}
              />
            )}
          </>
        )}
      </main>
    </div>
  )
}
