import { CloseCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { Button, Tag } from 'antd'

import type { DebugNodeState } from '../../../api/apps'

interface RunLogPanelProps {
  open: boolean
  running: boolean
  states: Record<string, DebugNodeState>
  finalResult: Record<string, unknown> | null
  onClose: () => void
}

const STATUS_COLOR: Record<DebugNodeState['status'], string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  error: 'error',
}

const STATUS_LABEL: Record<DebugNodeState['status'], string> = {
  pending: '等待',
  running: '运行中',
  success: '成功',
  error: '失败',
}

function extractUsage(output: Record<string, unknown>): string | null {
  if (!output || typeof output !== 'object') return null
  const usage = (output as { usage?: unknown }).usage
  if (!usage || typeof usage !== 'object') return null
  const u = usage as { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
  const parts: string[] = []
  if (u.prompt_tokens != null) parts.push(`prompt=${u.prompt_tokens}`)
  if (u.completion_tokens != null) parts.push(`completion=${u.completion_tokens}`)
  if (u.total_tokens != null) parts.push(`total=${u.total_tokens}`)
  return parts.length > 0 ? parts.join(' ') : null
}

export function RunLogPanel({ open, running, states, finalResult, onClose }: RunLogPanelProps) {
  if (!open) return null

  const items = Object.values(states)
  const finished = items.filter((s) => s.status === 'success' || s.status === 'error').length
  const total = items.length

  return (
    <div
      style={{
        borderTop: '1px solid #e8e8e8',
        background: '#fafafa',
        height: 220,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '6px 12px',
          borderBottom: '1px solid #f0f0f0',
          background: '#fff',
        }}
      >
        <strong style={{ fontSize: 13 }}>运行日志</strong>
        {running && <LoadingOutlined style={{ color: '#1677ff' }} />}
        <span style={{ fontSize: 12, color: '#8c8c8c' }}>
          进度：{finished}/{total}
        </span>
        <Button type="text" size="small" style={{ marginLeft: 'auto' }} onClick={onClose}>
          关闭面板
        </Button>
      </div>
      <div
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '8px 12px',
          fontFamily: 'monospace',
          fontSize: 12,
        }}
      >
        {items.length === 0 && !running && (
          <div style={{ color: '#999' }}>暂无日志，点击"试运行"开始执行</div>
        )}
        {items.map((item) => {
          const usage = item.status === 'success' ? extractUsage(item.output) : null
          return (
            <div key={item.node_id} style={{ marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Tag color={STATUS_COLOR[item.status]} style={{ marginInlineEnd: 0 }}>
                  {STATUS_LABEL[item.status]}
                </Tag>
                <strong>{item.node_id}</strong>
                <span style={{ color: '#999' }}>({item.type})</span>
                {item.status !== 'running' && item.duration_ms > 0 && (
                  <span style={{ color: '#999' }}>{item.duration_ms}ms</span>
                )}
                {usage && <span style={{ color: '#13c2c2' }}>{usage}</span>}
              </div>
              {item.error && (
                <div style={{ color: '#cf1322', marginTop: 4 }}>
                  <CloseCircleOutlined /> {item.error}
                </div>
              )}
              {item.status === 'success' && Object.keys(item.output).length > 0 && (
                <pre
                  style={{
                    margin: '4px 0 0 0',
                    padding: 6,
                    background: '#fff',
                    border: '1px solid #f0f0f0',
                    borderRadius: 4,
                    fontSize: 11,
                    maxHeight: 120,
                    overflow: 'auto',
                  }}
                >
                  {JSON.stringify(item.output, null, 2)}
                </pre>
              )}
            </div>
          )
        })}
        {finalResult && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 4, color: '#237804' }}>
              最终 outputs
            </div>
            <pre
              style={{
                margin: 0,
                padding: 8,
                background: '#f6ffed',
                border: '1px solid #b7eb8f',
                borderRadius: 4,
                fontSize: 11,
                maxHeight: 160,
                overflow: 'auto',
              }}
            >
              {JSON.stringify(finalResult, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}
