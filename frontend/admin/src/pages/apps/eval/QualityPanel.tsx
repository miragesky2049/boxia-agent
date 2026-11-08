import { useEffect, useState } from 'react'
import {
  Alert,
  Card,
  Descriptions,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  getQualitySummary,
  type QualityLowItem,
  type QualitySummary,
  type QualityTrendPoint,
} from '../../../api/eval'
import EvalCaptureButton from './EvalCaptureButton'

interface QualityPanelProps {
  applicationId: string
}

const statusLabels: Record<string, string> = { pass: '通过', fail: '未通过', error: '错误' }

function percentText(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)}%`
}

function scoreText(score: number | null | undefined): string {
  return score === null || score === undefined ? '—' : score.toFixed(2)
}

function timeText(value: string | null): string {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

/**
 * 质量看板（M4-d T-d9，F18.6）：评测批与线上采样概览 + 逐日均分趋势 +
 * 低分清单（飞轮入口：一键 from-run 转评测集，评测批即可消费）。
 */
export default function QualityPanel({ applicationId }: QualityPanelProps) {
  // null=未加载（含失败后保持 null 展示提示）；setState 全部在请求回调内
  const [summary, setSummary] = useState<QualitySummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(7)

  useEffect(() => {
    let cancelled = false
    setSummary(null)
    setError(null)
    getQualitySummary(applicationId, days)
      .then((data) => {
        if (!cancelled) setSummary(data)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [applicationId, days])

  if (error) return <Alert type="error" message={error} />
  if (!summary) return <Spin />

  const trendColumns = [
    { title: '日期', dataIndex: 'date', key: 'date' },
    { title: '样本数', dataIndex: 'count', key: 'count' },
    {
      title: '均分',
      key: 'avg',
      render: (_: unknown, row: QualityTrendPoint) => scoreText(row.avg_score),
    },
  ]
  const lowColumns = [
    {
      title: '问句',
      dataIndex: 'question',
      key: 'question',
      ellipsis: { showTitle: false },
      render: (value: string) => (
        <Tooltip title={value} placement="topLeft">
          <span>{value}</span>
        </Tooltip>
      ),
    },
    { title: '得分', dataIndex: 'score', key: 'score', width: 70 },
    {
      title: '判定',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (value: string) => <Tag>{statusLabels[value] ?? value}</Tag>,
    },
    {
      title: '理由',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: { showTitle: false },
      render: (value: string) => (
        <Tooltip title={value} placement="topLeft">
          <span>{value}</span>
        </Tooltip>
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (value: string | null) => timeText(value),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, row: QualityLowItem) => (
        <EvalCaptureButton applicationId={applicationId} runId={row.run_id} />
      ),
    },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <label htmlFor="quality-days-window">统计窗口</label>
        <Select
          id="quality-days-window"
          value={days}
          onChange={(value) => setDays(Number(value))}
          style={{ width: 120 }}
          options={[
            { value: 7, label: '近 7 天' },
            { value: 14, label: '近 14 天' },
            { value: 30, label: '近 30 天' },
          ]}
        />
      </Space>
      <Card
        size="small"
        title={`近 ${summary.window_days} 天质量概览`}
        style={{ marginBottom: 16 }}
      >
        <Descriptions column={3} size="small">
          <Descriptions.Item label="评测批次数">
            {String(summary.eval_batches.count)}
          </Descriptions.Item>
          <Descriptions.Item label="最新批通过率">
            {percentText(summary.eval_batches.latest_pass_rate)}
          </Descriptions.Item>
          <Descriptions.Item label="线上采样数">
            {String(summary.runtime_samples.count)}
          </Descriptions.Item>
          <Descriptions.Item label="采样平均分">
            {scoreText(summary.runtime_samples.avg_score)}
          </Descriptions.Item>
          <Descriptions.Item label="低分样本数">
            {String(summary.runtime_samples.low_score_count)}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card size="small" title="逐日采样均分" style={{ marginBottom: 16 }}>
        <Table<QualityTrendPoint>
          rowKey="date"
          size="small"
          columns={trendColumns}
          dataSource={summary.trend}
          pagination={false}
        />
      </Card>
      <Card size="small" title="低分清单（一键转评测集）">
        <Table<QualityLowItem>
          rowKey="run_id"
          size="small"
          columns={lowColumns}
          dataSource={summary.low_score_items}
          pagination={false}
          locale={{
            emptyText: <Typography.Text type="secondary">窗口内暂无低分样本</Typography.Text>,
          }}
        />
      </Card>
    </div>
  )
}
