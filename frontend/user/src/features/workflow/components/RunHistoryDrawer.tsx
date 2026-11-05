import { useState } from 'react'
import { CloseOutlined } from '@ant-design/icons'
import type { RunHistoryItem } from '../types'

const STATUS_TEXT: Record<RunHistoryItem['execute_status'], string> = {
  running: '运行中',
  success: '成功',
  error: '失败',
  interrupted: '待审批',
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function summarize(value: unknown, max: number): string {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (!text) return ''
  return text.length > max ? `${text.slice(0, max)}…` : text
}

function detailText(item: RunHistoryItem): string {
  const parts: string[] = []
  if (item.input) parts.push(`输入：${JSON.stringify(item.input, null, 2)}`)
  if (item.output) parts.push(`输出：${JSON.stringify(item.output, null, 2)}`)
  if (item.error_message) parts.push(`错误：${item.error_message}`)
  return parts.join('\n\n')
}

interface RunHistoryDrawerProps {
  open: boolean
  runs: RunHistoryItem[]
  approvals: RunHistoryItem[]
  onClose: () => void
  onSelectRun?: (item: RunHistoryItem) => void
  onApproveFromHistory?: (item: RunHistoryItem) => void
}

/** 运行历史抽屉：我的运行 / 待我审批双 Tab，展开查看输入输出详情。 */
export default function RunHistoryDrawer(props: RunHistoryDrawerProps) {
  const { open, runs, approvals, onClose, onSelectRun, onApproveFromHistory } = props
  const [tab, setTab] = useState<'runs' | 'approvals'>('runs')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const list = tab === 'runs' ? runs : approvals
  return (
    <>
      {open ? <button type="button" className="wf-drawer-backdrop" aria-label="关闭抽屉" onClick={onClose} /> : null}
      <aside className={`wf-drawer${open ? ' is-open' : ''}`} aria-hidden={!open}>
        <div className="wf-drawer__head">
          <span className="wf-drawer__title">运行历史</span>
          <button type="button" className="wf-drawer__close" onClick={onClose} aria-label="关闭">
            <CloseOutlined />
          </button>
        </div>
        <div className="wf-drawer__tabs">
          <button
            type="button"
            className={`wf-drawer__tab${tab === 'runs' ? ' is-active' : ''}`}
            onClick={() => setTab('runs')}
          >
            我的运行
          </button>
          <button
            type="button"
            className={`wf-drawer__tab${tab === 'approvals' ? ' is-active' : ''}`}
            onClick={() => setTab('approvals')}
          >
            待我审批
            {approvals.length > 0 ? <span className="wf-drawer__tab-badge">{approvals.length}</span> : null}
          </button>
        </div>
        <div className="wf-drawer__list">
          {list.length === 0 ? (
            <div className="wf-drawer__empty">{tab === 'runs' ? '还没有运行记录' : '没有待你审批的运行'}</div>
          ) : (
            list.map((item) => (
              <RunCard
                key={item.id}
                item={item}
                expanded={expandedId === item.id}
                isApprovalTab={tab === 'approvals'}
                onToggle={() => setExpandedId((prev) => (prev === item.id ? null : item.id))}
                onSelect={onSelectRun}
                onApprove={onApproveFromHistory}
              />
            ))
          )}
        </div>
      </aside>
    </>
  )
}

interface RunCardProps {
  item: RunHistoryItem
  expanded: boolean
  isApprovalTab: boolean
  onToggle: () => void
  onSelect?: (item: RunHistoryItem) => void
  onApprove?: (item: RunHistoryItem) => void
}

function RunCard(props: RunCardProps) {
  const { item, expanded, isApprovalTab, onToggle, onSelect, onApprove } = props
  const outputText = summarize(item.output, 60)
  const inputText = summarize(item.input, 60)
  return (
    <div className={`wf-run-card${expanded ? ' is-selected' : ''}`}>
      <button type="button" className="wf-run-card__head" style={{ width: '100%', border: 'none', background: 'transparent', fontFamily: 'inherit', cursor: 'pointer', padding: 0 }} onClick={onToggle}>
        <span className={`wf-run-card__status is-${item.execute_status}`}>
          <span className="wf-run-card__status-dot" aria-hidden="true" />
          {STATUS_TEXT[item.execute_status]}
        </span>
        <span className="wf-run-card__time">{formatTime(item.started_at)}</span>
      </button>
      <div className="wf-run-card__summary">
        {inputText ? (
          <span>
            <b>输入：</b>
            {inputText}
          </span>
        ) : null}
        {outputText ? (
          <span>
            <b>输出：</b>
            {outputText}
          </span>
        ) : null}
        {item.error_message ? (
          <span>
            <b>错误：</b>
            {item.error_message}
          </span>
        ) : null}
      </div>
      {expanded ? (
        <div className="wf-drawer__detail">
          <pre className="wf-drawer__detail-pre">{detailText(item) || '无详细数据'}</pre>
        </div>
      ) : null}
      {isApprovalTab || item.execute_status === 'interrupted' ? (
        <div className="wf-run-card__actions">
          {onSelect ? (
            <button type="button" className="wf-btn wf-btn--ghost" onClick={() => onSelect(item)}>
              查看轨迹
            </button>
          ) : null}
          {onApprove ? (
            <button type="button" className="wf-btn wf-btn--primary" onClick={() => onApprove(item)}>
              去审批
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
