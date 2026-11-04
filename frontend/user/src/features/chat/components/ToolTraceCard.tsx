import {
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  RightOutlined,
} from '@ant-design/icons'
import { useState } from 'react'
import type { ToolTrace } from '../types'

function TraceIcon({ status }: { status: ToolTrace['status'] }) {
  if (status === 'running') return <span className="lc-spinner" aria-hidden />
  if (status === 'error') return <CloseOutlined className="lc-trace__icon is-error" />
  return <CheckOutlined className="lc-trace__icon is-done" />
}

function headerLabel(trace: ToolTrace): string {
  if (trace.status === 'running') return `正在调用 ${trace.name}…`
  if (trace.status === 'error') return `${trace.name} 调用失败`
  const seconds = trace.durationMs ? (trace.durationMs / 1000).toFixed(1) : null
  return seconds ? `${trace.name} · ${seconds}s` : `${trace.name} 已完成`
}

export function ToolTraceCard({ trace }: { trace: ToolTrace }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetail = Boolean(trace.args || trace.result || trace.error)

  return (
    <div className={`lc-trace is-${trace.status}`}>
      <button
        type="button"
        className="lc-trace__header"
        onClick={() => hasDetail && setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        <TraceIcon status={trace.status} />
        <span className="lc-trace__label">{headerLabel(trace)}</span>
        {hasDetail && (
          <span className="lc-trace__chevron" aria-hidden>
            {expanded ? <DownOutlined /> : <RightOutlined />}
          </span>
        )}
      </button>

      {expanded && hasDetail && (
        <div className="lc-trace__body">
          {trace.args && (
            <div className="lc-trace__block">
              <span className="lc-trace__block-label">参数</span>
              <pre>{trace.args}</pre>
            </div>
          )}
          {trace.result && (
            <div className="lc-trace__block">
              <span className="lc-trace__block-label">结果</span>
              <pre>{trace.result}</pre>
            </div>
          )}
          {trace.error && (
            <div className="lc-trace__block is-error">
              <span className="lc-trace__block-label">错误</span>
              <pre>{trace.error}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
