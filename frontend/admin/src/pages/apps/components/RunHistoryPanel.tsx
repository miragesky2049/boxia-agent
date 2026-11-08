import { useCallback, useEffect, useState } from 'react'
import { Button, Collapse, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getRunDetail,
  listApplicationRuns,
  type NodeExecution,
  type RunDetail,
  type RunItem,
} from '../../../api/apps'
import { CANVAS_TOKENS } from '../canvas/tokens'

// 0074 PRD F13：键名与后端 execute_status 对齐，cancelled=断连取消
const STATUS_VIEW: Record<RunItem['execute_status'], { text: string; color: string }> = {
  running: { text: '运行中', color: CANVAS_TOKENS.info },
  success: { text: '成功', color: CANVAS_TOKENS.run },
  error: { text: '失败', color: CANVAS_TOKENS.danger },
  interrupted: { text: '已中断', color: CANVAS_TOKENS.warning },
  cancelled: { text: '已取消', color: '#6b7280' },
}

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('MM-DD HH:mm:ss') : '-'
}

function formatDuration(run: RunItem): string {
  if (!run.finished_at) return '-'
  const ms = dayjs(run.finished_at).diff(dayjs(run.started_at))
  if (!Number.isFinite(ms) || ms < 0) return '-'
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ color: '#9ca3af' }}>{label}</div>
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}

function executionItems(executions: NodeExecution[]) {
  return executions.map((exec) => ({
    key: exec.id,
    label: (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
        <span style={{ fontFamily: 'monospace' }}>{exec.node_id}</span>
        <span style={{ color: '#9ca3af' }}>{exec.node_type}</span>
        {exec.duration_ms != null && (
          <span style={{ color: '#9ca3af', marginLeft: 'auto' }}>{exec.duration_ms}ms</span>
        )}
        {exec.error_message && <span style={{ color: CANVAS_TOKENS.danger }}>失败</span>}
      </div>
    ),
    children: (
      <div style={{ fontSize: 11, fontFamily: 'monospace' }}>
        <JsonBlock label="输入：" value={exec.input} />
        <JsonBlock label="输出：" value={exec.output} />
        {exec.error_message && (
          <div style={{ color: CANVAS_TOKENS.danger }}>
            <div>错误：</div>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {exec.error_message}
            </pre>
          </div>
        )}
      </div>
    ),
  }))
}

interface RunHistoryPanelProps {
  applicationId: string
  // 面板切到「历史」Tab 时才拉数据，避免无谓请求
  active: boolean
}

export function RunHistoryPanel({ applicationId, active }: RunHistoryPanelProps) {
  const [runs, setRuns] = useState<RunItem[]>([])
  const [loading, setLoading] = useState(false)
  const [openRunId, setOpenRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRuns(await listApplicationRuns(applicationId, 20))
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载运行历史失败')
    } finally {
      setLoading(false)
    }
  }, [applicationId])

  useEffect(() => {
    if (active) void load()
  }, [active, load])

  const toggleRun = useCallback(
    async (runId: string) => {
      if (openRunId === runId) {
        setOpenRunId(null)
        setDetail(null)
        return
      }
      setOpenRunId(runId)
      setDetail(null)
      setDetailLoading(true)
      try {
        setDetail(await getRunDetail(runId))
      } catch (err) {
        message.error(err instanceof Error ? err.message : '加载运行详情失败')
      } finally {
        setDetailLoading(false)
      }
    },
    [openRunId],
  )

  if (runs.length === 0) {
    return (
      <div style={{ color: '#9ca3af', fontSize: 12, textAlign: 'center', padding: 16 }}>
        {loading ? '加载中…' : '暂无运行记录'}
        {!loading && (
          <div style={{ marginTop: 8 }}>
            <Button size="small" type="text" icon={<ReloadOutlined />} onClick={() => void load()}>
              刷新
            </Button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ fontSize: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
        <Button
          size="small"
          type="text"
          icon={<ReloadOutlined />}
          loading={loading}
          onClick={() => void load()}
        >
          刷新
        </Button>
      </div>
      {runs.map((run) => {
        const status = STATUS_VIEW[run.execute_status] || {
          text: run.execute_status,
          color: '#6b7280',
        }
        const expanded = openRunId === run.id
        return (
          <div key={run.id} style={{ borderBottom: '1px dashed #f3f4f6', padding: '6px 0' }}>
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}
              onClick={() => void toggleRun(run.id)}
            >
              <span
                style={{ width: 8, height: 8, borderRadius: '50%', background: status.color }}
              />
              <span style={{ color: status.color }}>{status.text}</span>
              <span style={{ color: '#9ca3af' }}>{formatTime(run.started_at)}</span>
              <span style={{ color: '#9ca3af', marginLeft: 'auto' }}>{formatDuration(run)}</span>
              <span style={{ color: '#9ca3af', fontSize: 11 }}>{expanded ? '收起' : '详情'}</span>
            </div>
            {expanded && (
              <div style={{ marginTop: 6 }}>
                {detailLoading && <div style={{ color: '#9ca3af' }}>加载中…</div>}
                {!detailLoading && detail && (
                  <>
                    <JsonBlock label="入参：" value={detail.run.input} />
                    <JsonBlock label="出参：" value={detail.run.output} />
                    {detail.run.error_message && (
                      <div style={{ color: CANVAS_TOKENS.danger, marginBottom: 6 }}>
                        错误：{detail.run.error_message}
                      </div>
                    )}
                    {detail.node_executions.length > 0 ? (
                      <Collapse size="small" items={executionItems(detail.node_executions)} />
                    ) : (
                      <div style={{ color: '#9ca3af' }}>无节点执行记录</div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
