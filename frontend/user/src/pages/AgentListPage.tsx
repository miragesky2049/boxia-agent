import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { listAgents } from '../api/agents'
import type { UserAgentSummary } from '../api/types'
import AppHeader from '../components/AppHeader'

const PAGE_SIZE = 12

function formatDescription(value: string): string {
  return value.trim() || '暂无简介'
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

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPage(1)
    setKeyword(searchInput.trim())
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="app">
      <AppHeader />
      <main className="container">
        <section className="hero">
          <div>
            <h1>可用智能体</h1>
            <p>这里只展示你的角色被授权且已启用的智能体。</p>
          </div>
          <form className="search" onSubmit={handleSearch} role="search">
            <input
              value={searchInput}
              placeholder="搜索智能体名称"
              maxLength={100}
              onChange={(event) => setSearchInput(event.target.value)}
            />
            <button type="submit" className="button">
              搜索
            </button>
          </form>
        </section>

        {error && (
          <div className="notice notice--error" role="alert">
            <span>{error}</span>
            <button type="button" className="button button--ghost" onClick={() => void load()}>
              重试
            </button>
          </div>
        )}

        {loading ? (
          <p className="state-text">正在加载智能体…</p>
        ) : items.length === 0 ? (
          <div className="empty">
            <p>{keyword ? '没有匹配的智能体' : '暂无可用的智能体'}</p>
            <span>如长时间为空，请联系租户管理员确认角色授权。</span>
          </div>
        ) : (
          <div className="agent-grid">
            {items.map((agent) => (
              <Link key={agent.id} to={`/agents/${agent.id}`} className="agent-card">
                <div className="agent-card__head">
                  {agent.avatar_url ? (
                    <img src={agent.avatar_url} alt="" className="agent-card__avatar" />
                  ) : (
                    <span className="agent-card__avatar agent-card__avatar--fallback">
                      {agent.name.slice(0, 1)}
                    </span>
                  )}
                  <h2>{agent.name}</h2>
                </div>
                <p>{formatDescription(agent.description)}</p>
                <span className="agent-card__more">查看详情 →</span>
              </Link>
            ))}
          </div>
        )}

        {totalPages > 1 && (
          <nav className="pager" aria-label="分页">
            <button
              type="button"
              className="button button--ghost"
              disabled={page <= 1 || loading}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              上一页
            </button>
            <span>
              第 {page} / {totalPages} 页 · 共 {total} 个
            </span>
            <button
              type="button"
              className="button button--ghost"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            >
              下一页
            </button>
          </nav>
        )}
      </main>
    </div>
  )
}
