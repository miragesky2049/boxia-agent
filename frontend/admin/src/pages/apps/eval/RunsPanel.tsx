import { useCallback, useEffect, useState } from 'react'
import { App, Button, Descriptions, Drawer, Form, InputNumber, Modal, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { listGraphVersions } from '../../../api/apps'
import {
  diffEvalRuns,
  getEvalRunDetail,
  listDatasets,
  listEvalRuns,
  listEvaluators,
  startEvalRun,
  type EvalDiffItem,
  type EvalDataset,
  type EvalRun,
  type EvalRunDetail,
} from '../../../api/eval'

interface RunsPanelProps {
  applicationId: string
}

const STATUS_TEXT: Record<string, string> = {
  pending: '排队中',
  running: '运行中',
  completed: '已完成',
  error: '失败',
}

// 后端 eval_result.status 为 pass/fail/error（eval_run_service），报告与 diff 表格统一中文映射
const RESULT_TEXT: Record<string, string> = {
  pass: '通过',
  fail: '未通过',
  error: '异常',
}

// 与后端 MIN/MAX_CONCURRENCY 对齐（schema ge=2 le=8，服务侧 clamp 2~4）
const MinConcurrency = 2
const MaxConcurrency = 8
const PollIntervalMs = 5000

function percentText(rate: number): string {
  return `${Math.round(rate * 100)}%`
}

/**
 * 评测运行页签：发起（锁数据集×图版本×评估器）+ running 轮询 + 报告抽屉 + 两批 diff（F18.4/F18.5）。
 */
export default function RunsPanel({ applicationId }: RunsPanelProps) {
  const { message } = App.useApp()
  // null=加载中；数据只在请求回调里落 state，避免 effect 同步 setState 级联渲染
  const [runs, setRuns] = useState<EvalRun[] | null>(null)
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])

  const [startOpen, setStartOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [versionOptions, setVersionOptions] = useState<{ value: number; label: string }[]>([])
  const [evaluatorOptions, setEvaluatorOptions] = useState<{ value: string; label: string }[]>([])
  const [startForm] = Form.useForm()

  const [detail, setDetail] = useState<EvalRunDetail | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [diffItems, setDiffItems] = useState<EvalDiffItem[] | null>(null)
  const [diffOpen, setDiffOpen] = useState(false)

  const datasetName = useCallback(
    (datasetId: string) => datasets.find((d) => d.id === datasetId)?.name ?? datasetId.slice(0, 8),
    [datasets],
  )

  const load = useCallback(() => {
    Promise.all([listEvalRuns(applicationId), listDatasets(applicationId)])
      .then(([runItems, datasetItems]) => {
        setRuns(runItems)
        setDatasets(datasetItems)
      })
      .catch((err: Error) => {
        message.error(err.message)
        setRuns((prev) => prev ?? [])
      })
  }, [applicationId, message])

  useEffect(() => {
    load()
  }, [load])

  const hasActive = (runs ?? []).some((r) => r.status === 'running' || r.status === 'pending')
  useEffect(() => {
    if (!hasActive) return
    const timer = setInterval(load, PollIntervalMs)
    return () => clearInterval(timer)
  }, [hasActive, load])

  const openStart = async () => {
    setStartOpen(true)
    // Modal 未打开时 Form 未挂载，延后 setFieldsValue 避免 antd not-connected 告警（同 AppListPage 先例）
    requestAnimationFrame(() => {
      startForm.setFieldsValue({ concurrency: MinConcurrency })
    })
    try {
      const [versions, evaluators] = await Promise.all([listGraphVersions(applicationId), listEvaluators()])
      setVersionOptions(versions.map((v) => ({ value: v.version, label: `版本 ${v.version}` })))
      setEvaluatorOptions(evaluators.map((e) => ({ value: e.id, label: e.name })))
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const handleStart = async () => {
    let values: {
      dataset_id: string
      graph_version: number
      evaluator_ids: string[]
      concurrency?: number
    }
    try {
      values = await startForm.validateFields()
    } catch (error) {
      // 字段校验失败时表单项已有内联错误提示，静默返回（同 AppListPage 先例）
      if (error && (error as { errorFields?: unknown }).errorFields) return
      message.error(error instanceof Error ? error.message : '校验发起参数失败')
      return
    }
    // 发起即投递计费批，POST 在途期间禁用确定按钮防双击重复建批
    setSubmitting(true)
    try {
      await startEvalRun({
        dataset_id: values.dataset_id,
        graph_version: values.graph_version,
        evaluator_ids: values.evaluator_ids,
        concurrency: values.concurrency ?? MinConcurrency,
      })
      message.success('评测运行已发起')
      setStartOpen(false)
      startForm.resetFields()
      load()
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const openDetail = async (runId: string) => {
    try {
      setDetail(await getEvalRunDetail(runId))
      setDetailOpen(true)
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  // 勾满两条后再勾第三条时挤掉最早的，保证 run_a/run_b 语义始终是"最近两次勾选顺序"
  const toggleSelect = (runId: string, selected: boolean) => {
    setSelectedKeys((prev) => {
      if (!selected) return prev.filter((k) => k !== runId)
      return [...prev, runId].slice(-2)
    })
  }

  const handleDiff = async () => {
    const [runA, runB] = selectedKeys
    if (!runA || !runB) return
    try {
      setDiffItems(await diffEvalRuns(runA, runB))
      setDiffOpen(true)
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const columns: ColumnsType<EvalRun> = [
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => STATUS_TEXT[status] ?? status,
    },
    { title: '数据集', dataIndex: 'dataset_id', render: (id: string) => datasetName(id) },
    { title: '图版本', dataIndex: 'graph_version', width: 90 },
    {
      title: '进度',
      key: 'progress',
      width: 100,
      render: (_, record) => {
        const p = record.progress
        // 批发起时 progress 仅含 concurrency，total 未定时显示 0/0 会误导为"空批"
        if (!p || p.total == null) return '—'
        return `${p.done ?? 0}/${p.total}`
      },
    },
    {
      title: '错误',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (v: string | null) => v ?? '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => void openDetail(record.id)}>
          详情
        </Button>
      ),
    },
  ]

  const diffColumns: ColumnsType<EvalDiffItem> = [
    { title: '序号', dataIndex: 'position', width: 70 },
    {
      title: 'A 状态',
      dataIndex: 'status_a',
      width: 90,
      render: (status: string | null) => (status ? (RESULT_TEXT[status] ?? status) : '—'),
    },
    {
      title: 'B 状态',
      dataIndex: 'status_b',
      width: 90,
      render: (status: string | null) => (status ? (RESULT_TEXT[status] ?? status) : '—'),
    },
    { title: 'A 原因', dataIndex: 'reason_a', ellipsis: true, render: (v: string | null) => v ?? '—' },
    { title: 'B 原因', dataIndex: 'reason_b', ellipsis: true, render: (v: string | null) => v ?? '—' },
  ]

  const resultColumns: ColumnsType<EvalRunDetail['results'][number]> = [
    {
      title: '用例',
      dataIndex: 'case_id',
      render: (id: string | null) => (id ? id.slice(0, 8) : '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (status: string) => RESULT_TEXT[status] ?? status,
    },
    { title: '分数', dataIndex: 'score', width: 80, render: (v: number | null) => (v === null ? '—' : v) },
    { title: '原因', dataIndex: 'reason', ellipsis: true },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space>
        <Button type="primary" onClick={() => void openStart()}>
          发起评测运行
        </Button>
        <Button disabled={selectedKeys.length !== 2} onClick={() => void handleDiff()}>
          对比选中
        </Button>
      </Space>
      <Table
        rowKey="id"
        loading={runs === null}
        columns={columns}
        dataSource={runs ?? []}
        size="small"
        pagination={false}
        rowSelection={{
          type: 'checkbox',
          selectedRowKeys: selectedKeys,
          // 对比语义最多两条，表头全选与"挤掉最早"规则冲突，隐藏全选框
          hideSelectAll: true,
          onSelect: (record, selected) => toggleSelect(String(record.id), selected),
        }}
      />

      <Modal
        title="发起评测运行"
        open={startOpen}
        okText="发起"
        confirmLoading={submitting}
        onOk={() => void handleStart()}
        onCancel={() => {
          setStartOpen(false)
          startForm.resetFields()
        }}
      >
        <Form form={startForm} layout="vertical">
          <Form.Item name="dataset_id" label="数据集" rules={[{ required: true, message: '请选择数据集' }]}>
            <Select
              placeholder="选择数据集"
              options={datasets.map((d) => ({ value: d.id, label: d.name }))}
            />
          </Form.Item>
          <Form.Item name="graph_version" label="图版本" rules={[{ required: true, message: '请选择已发布版本' }]}>
            <Select placeholder="选择发布版本" options={versionOptions} />
          </Form.Item>
          <Form.Item name="evaluator_ids" label="评估器" rules={[{ required: true, message: '至少选择一个评估器' }]}>
            <Select mode="multiple" placeholder="选择评估器" options={evaluatorOptions} />
          </Form.Item>
          <Form.Item name="concurrency" label="并发数" tooltip="执行侧当前串行消费，仅记录意图">
            <InputNumber min={MinConcurrency} max={MaxConcurrency} placeholder="并发数" />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title="评测报告" open={detailOpen} width={720} onClose={() => setDetailOpen(false)}>
        {detail ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Descriptions column={3} size="small">
              <Descriptions.Item label="通过率">{percentText(detail.summary.pass_rate)}</Descriptions.Item>
              <Descriptions.Item label="通过">{String(detail.summary.passed)}</Descriptions.Item>
              <Descriptions.Item label="失败">{String(detail.summary.failed)}</Descriptions.Item>
            </Descriptions>
            <Table
              rowKey="id"
              size="small"
              columns={resultColumns}
              dataSource={detail.results}
              pagination={false}
            />
          </Space>
        ) : null}
      </Drawer>

      <Modal
        title={`运行对比 ${selectedKeys[0]?.slice(0, 8) ?? ''} vs ${selectedKeys[1]?.slice(0, 8) ?? ''}`}
        open={diffOpen}
        footer={null}
        width={720}
        onCancel={() => setDiffOpen(false)}
      >
        <Table rowKey="case_id" size="small" columns={diffColumns} dataSource={diffItems ?? []} pagination={false} />
      </Modal>
    </Space>
  )
}
