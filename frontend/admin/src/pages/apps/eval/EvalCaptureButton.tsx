import { useState } from 'react'
import { App, Alert, Button, Modal, Radio, Space } from 'antd'
import { captureCaseFromRun, listDatasets, type EvalDataset } from '../../../api/eval'

interface EvalCaptureButtonProps {
  applicationId: string
  runId: string
}

/**
 * run 记录「加入评测集」按钮（F18.2 冷启动捕获）：选定数据集后把该 run 的
 * 问句与产出物化为评测用例；捕获校验（同应用/success/问句非空）由后端兜底。
 */
export default function EvalCaptureButton({ applicationId, runId }: EvalCaptureButtonProps) {
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [datasets, setDatasets] = useState<EvalDataset[]>([])
  const [picked, setPicked] = useState<string | null>(null)

  const openModal = async () => {
    setOpen(true)
    setPicked(null)
    setLoading(true)
    try {
      setDatasets(await listDatasets(applicationId))
    } catch (err) {
      message.error((err as Error).message)
      setDatasets([])
    } finally {
      setLoading(false)
    }
  }

  const handleCapture = async () => {
    if (!picked) return
    setSubmitting(true)
    try {
      await captureCaseFromRun(picked, runId)
      message.success('已加入评测集')
      setOpen(false)
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <Button type="link" size="small" onClick={() => void openModal()}>
        加入评测集
      </Button>
      <Modal
        title="加入评测集"
        open={open}
        okText="导入"
        okButtonProps={{ disabled: datasets.length === 0 }}
        confirmLoading={submitting}
        onOk={() => void handleCapture()}
        onCancel={() => setOpen(false)}
      >
        {datasets.length === 0 && !loading ? (
          <Alert type="info" message="还没有评测数据集，请先在「智能体评测」工作区创建" />
        ) : (
          <Radio.Group value={picked} onChange={(event) => setPicked(String(event.target.value))}>
            <Space direction="vertical">
              {datasets.map((dataset) => (
                <Radio key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        )}
      </Modal>
    </>
  )
}
