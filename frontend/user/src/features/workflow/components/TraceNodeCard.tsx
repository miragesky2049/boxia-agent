import { useState } from 'react'
import { CheckOutlined, CloseOutlined, DownOutlined, RightOutlined } from '@ant-design/icons'
import type { WorkflowNodeState } from '../types'

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return '（无）'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function statusLabel(node: WorkflowNodeState): string {
  if (node.status === 'running') return '执行中'
  return node.status === 'success' ? '成功' : '失败'
}

interface TraceNodeCardProps {
  node: WorkflowNodeState
}

/** 时间线单节点卡：状态圆点 + 摘要行 + 可展开的入出参/流式文本。 */
export default function TraceNodeCard(props: TraceNodeCardProps) {
  const { node } = props
  const [open, setOpen] = useState(false)
  const showStream = node.nodeType === 'llm' && node.streamingText.length > 0
  const hasBody = showStream || node.inputs !== undefined || node.outputs !== undefined || !!node.error
  return (
    <div className={`wf-node${node.status === 'error' ? ' is-error' : ''}`}>
      <span className={`wf-node__marker is-${node.status}`} aria-hidden="true">
        {node.status === 'success' ? <CheckOutlined /> : null}
        {node.status === 'error' ? <CloseOutlined /> : null}
      </span>
      <div className="wf-node__card">
        <button
          type="button"
          className="wf-node__summary"
          onClick={() => setOpen((v) => !v)}
          disabled={!hasBody}
          style={hasBody ? undefined : { cursor: 'default' }}
        >
          <span className="wf-node__title">{node.title || node.nodeId}</span>
          {node.nodeType ? <span className="wf-node__type">{node.nodeType}</span> : null}
          {node.status === 'running' ? <span className="wf-spinner" aria-hidden="true" /> : null}
          <span className="wf-node__duration">
            {node.status === 'running'
              ? statusLabel(node)
              : node.durationMs !== undefined
                ? `${node.durationMs} ms`
                : statusLabel(node)}
          </span>
          {hasBody ? (
            <span className="wf-node__chevron" aria-hidden="true">
              {open ? <DownOutlined /> : <RightOutlined />}
            </span>
          ) : null}
        </button>
        {open && hasBody ? (
          <div className="wf-node__body">
            {showStream ? (
              <div className="wf-node__section">
                <span className="wf-node__section-label">流式输出</span>
                <div className="wf-node__stream">{node.streamingText}</div>
              </div>
            ) : null}
            {node.inputs !== undefined ? (
              <div className="wf-node__section">
                <span className="wf-node__section-label">输入</span>
                <pre className="wf-node__pre">{formatJson(node.inputs)}</pre>
              </div>
            ) : null}
            {node.outputs !== undefined ? (
              <div className="wf-node__section">
                <span className="wf-node__section-label">输出</span>
                <pre className="wf-node__pre">{formatJson(node.outputs)}</pre>
              </div>
            ) : null}
            {node.error ? (
              <div className="wf-node__section">
                <span className="wf-node__section-label">错误</span>
                <pre className="wf-node__pre is-error">{node.error}</pre>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  )
}
