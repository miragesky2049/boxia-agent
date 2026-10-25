import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAgent } from '../api/agents'
import type { UserAgentDetail, UserPrompt, UserSkill, UserTool } from '../api/types'
import AppHeader from '../components/AppHeader'

function ResourceSection<T extends { id: string; name: string; description: string }>({
  title,
  hint,
  items,
  renderExtra,
}: {
  title: string
  hint: string
  items: T[]
  renderExtra?: (item: T) => ReactNode
}) {
  if (items.length === 0) return null
  return (
    <section className="resource-section">
      <header>
        <h2>{title}</h2>
        <span>{hint}</span>
      </header>
      <div className="resource-grid">
        {items.map((item) => (
          <article key={item.id} className="resource-card">
            <h3>{item.name}</h3>
            <p>{item.description.trim() || '暂无描述'}</p>
            {renderExtra?.(item)}
          </article>
        ))}
      </div>
    </section>
  )
}

function TextContent({ content }: { content: string }) {
  if (!content.trim()) return null
  return (
    <details className="resource-content">
      <summary>查看内容</summary>
      <pre>{content}</pre>
    </details>
  )
}

function renderSkillExtra(item: UserSkill) {
  return <TextContent content={item.content} />
}

function renderPromptExtra(item: UserPrompt) {
  return (
    <>
      <span className="tag">{item.category || '未分类'}</span>
      {item.variables.length > 0 && (
        <p className="resource-meta">变量：{item.variables.join('、')}</p>
      )}
      <TextContent content={item.content} />
    </>
  )
}

function renderToolExtra(item: UserTool) {
  return <span className="tag">{item.type || '未指定类型'}</span>
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

  const resourceTotal =
    (agent?.skills.length ?? 0) +
    (agent?.tools.length ?? 0) +
    (agent?.components.length ?? 0) +
    (agent?.prompts.length ?? 0)

  return (
    <div className="app">
      <AppHeader />
      <main className="container">
        <Link to="/" className="back-link">
          ← 返回智能体列表
        </Link>

        {loading ? (
          <p className="state-text">正在加载智能体详情…</p>
        ) : error || !agent ? (
          <div className="notice notice--error" role="alert">
            <span>{error ?? '智能体不存在或未授权'}</span>
          </div>
        ) : (
          <>
            <section className="detail-head">
              {agent.avatar_url ? (
                <img src={agent.avatar_url} alt="" className="detail-avatar" />
              ) : (
                <span className="detail-avatar detail-avatar--fallback">
                  {agent.name.slice(0, 1)}
                </span>
              )}
              <div>
                <h1>{agent.name}</h1>
                <p>{agent.description.trim() || '暂无简介'}</p>
                <span className="tag">
                  {resourceTotal > 0 ? `${resourceTotal} 项可用资源` : '暂未配置资源'}
                </span>
              </div>
            </section>

            {resourceTotal === 0 ? (
              <div className="empty">
                <p>该智能体暂未配置对你可见的技能、工具、组件或提示词。</p>
                <span>如需使用，请联系租户管理员补充角色授权。</span>
              </div>
            ) : (
              <>
                <ResourceSection
                  title="技能"
                  hint="按角色授权后可见"
                  items={agent.skills}
                  renderExtra={renderSkillExtra}
                />
                <ResourceSection
                  title="工具"
                  hint="调用能力"
                  items={agent.tools}
                  renderExtra={renderToolExtra}
                />
                <ResourceSection
                  title="组件"
                  hint="可复用交互组件"
                  items={agent.components}
                  renderExtra={renderToolExtra}
                />
                <ResourceSection
                  title="提示词"
                  hint="内置提示词模板"
                  items={agent.prompts}
                  renderExtra={renderPromptExtra}
                />
              </>
            )}
          </>
        )}
      </main>
    </div>
  )
}
