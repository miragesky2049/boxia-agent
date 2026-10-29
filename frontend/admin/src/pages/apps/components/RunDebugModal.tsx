import { LoadingOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { App, Button, Input, Modal } from 'antd'
import { useEffect, useState } from 'react'

import {
  debugRunAppStream,
  type DebugNodeState,
  type Graph,
} from '../../../api/apps'

interface RunDebugModalProps {
  open: boolean
  graph: Graph
  onClose: () => void
  onNodeStateChange: (states: Record<string, DebugNodeState>) => void
  onRunningChange: (running: boolean) => void
  onFinalResult: (result: Record<string, unknown> | null) => void
}

export function RunDebugModal({
  open,
  graph,
  onClose,
  onNodeStateChange,
  onRunningChange,
  onFinalResult,
}: RunDebugModalProps) {
  const { message } = App.useApp()
  const [inputsText, setInputsText] = useState('{}')
  const [running, setRunning] = useState(false)
  const [states, setStates] = useState<Record<string, DebugNodeState>>({})

  // 关闭弹窗时保留上次运行的节点状态与最终结果，运行日志面板仍可查看；
  // 只有再次点击"开始试运行"时才会清空重新跑
  useEffect(() => {
    onRunningChange(running)
  }, [running, onRunningChange])

  useEffect(() => {
    onNodeStateChange(states)
  }, [states, onNodeStateChange])

  const handleRun = async () => {
    let inputs: Record<string, unknown>
    try {
      inputs = JSON.parse(inputsText || '{}')
    } catch {
      message.error('入参必须是合法 JSON')
      return
    }
    setRunning(true)
    setStates({})
    onFinalResult(null)
    try {
      await debugRunAppStream({ graph, inputs }, (evt) => {
        if (evt.event === 'node_start') {
          const nodeId = String(evt.data.node_id ?? '')
          if (!nodeId) return
          setStates((prev) => ({
            ...prev,
            [nodeId]: {
              node_id: nodeId,
              type: String(evt.data.type ?? ''),
              status: 'running',
              duration_ms: 0,
              output: {},
              error: '',
            },
          }))
        } else if (evt.event === 'node_end') {
          const nodeId = String(evt.data.node_id ?? '')
          if (!nodeId) return
          const status = String(evt.data.status ?? 'success') as DebugNodeState['status']
          setStates((prev) => ({
            ...prev,
            [nodeId]: {
              node_id: nodeId,
              type: String(evt.data.type ?? prev[nodeId]?.type ?? ''),
              status,
              duration_ms: Number(evt.data.duration_ms ?? 0),
              output: (evt.data.output as Record<string, unknown>) ?? {},
              error: String(evt.data.error ?? ''),
            },
          }))
        } else if (evt.event === 'result') {
          onFinalResult((evt.data.outputs as Record<string, unknown>) ?? {})
        } else if (evt.event === 'error') {
          message.error(String(evt.data.message ?? '试运行失败'))
        }
      })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '试运行启动失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal
      title="应用试运行"
      open={open}
      onCancel={onClose}
      footer={
        <>
          <Button onClick={onClose}>关闭</Button>
          <Button
            type="primary"
            icon={running ? <LoadingOutlined /> : <PlayCircleOutlined />}
            loading={running}
            onClick={handleRun}
          >
            {running ? '运行中...' : '开始试运行'}
          </Button>
        </>
      }
      width={560}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ marginBottom: 4, fontSize: 13, color: '#595959' }}>
          入参 JSON（会作为 input 传入 start 节点）
        </div>
        <Input.TextArea
          value={inputsText}
          onChange={(e) => setInputsText(e.target.value)}
          rows={4}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
          placeholder='{ "query": "你好" }'
          disabled={running}
        />
      </div>
    </Modal>
  )
}
