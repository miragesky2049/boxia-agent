import { CloseCircleOutlined, LoadingOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { App, Button, Drawer, Input, List, Modal, Tag } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import {
  debugRunWorkflowStream,
  type WorkflowDebugNodeState,
} from '../../../api/workflows'
import type { WorkflowGraph } from '../../../api/workflows'

interface RunDebugModalProps {
  open: boolean
  graph: WorkflowGraph
  onClose: () => void
  onNodeStateChange: (states: Record<string, WorkflowDebugNodeState>) => void
}

const STATUS_COLOR: Record<WorkflowDebugNodeState['status'], string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  error: 'error',
}

const STATUS_LABEL: Record<WorkflowDebugNodeState['status'], string> = {
  pending: '等待',
  running: '运行中',
  success: '成功',
  error: '失败',
}

export function RunDebugModal({
  open,
  graph,
  onClose,
  onNodeStateChange,
}: RunDebugModalProps) {
  const { message } = App.useApp()
  const [inputsText, setInputsText] = useState('{}')
  const [running, setRunning] = useState(false)
  const [states, setStates] = useState<Record<string, WorkflowDebugNodeState>>({})
  const [finalResult, setFinalResult] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    if (!open) {
      setStates({})
      setFinalResult(null)
      setRunning(false)
    }
  }, [open])

  useEffect(() => {
    onNodeStateChange(states)
  }, [states, onNodeStateChange])

  const requiredInputs = useMemo(
    () => (graph.variables ?? []).filter((v) => v.required).map((v) => v.key),
    [graph],
  )

  const finishedCount = useMemo(
    () => Object.values(states).filter((s) => s.status === 'success' || s.status === 'error').length,
    [states],
  )
  const totalCount = useMemo(() => graph.nodes?.length ?? 0, [graph])

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
    setFinalResult(null)
    try {
      await debugRunWorkflowStream({ graph, inputs }, (evt) => {
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
          const status = String(evt.data.status ?? 'success') as WorkflowDebugNodeState['status']
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
          setFinalResult((evt.data.outputs as Record<string, unknown>) ?? {})
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
    <>
      <Modal
        title="工作流试运行"
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
            入参 JSON（必填字段：{requiredInputs.length ? requiredInputs.join(', ') : '无'}）
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
        <div style={{ fontSize: 12, color: '#8c8c8c' }}>
          进度：{finishedCount}/{totalCount} 节点
        </div>
      </Modal>

      <Drawer
        title="节点执行详情"
        placement="right"
        width={420}
        open={Object.keys(states).length > 0}
        onClose={() => onNodeStateChange({})}
      >
        <List
          dataSource={Object.values(states)}
          renderItem={(item) => (
            <List.Item>
              <div style={{ width: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Tag color={STATUS_COLOR[item.status]} bordered={false}>
                    {STATUS_LABEL[item.status]}
                  </Tag>
                  <strong>{item.node_id}</strong>
                  <span style={{ color: '#999', fontSize: 12 }}>({item.type})</span>
                  {item.status !== 'running' && item.duration_ms > 0 && (
                    <span style={{ marginLeft: 'auto', fontSize: 12, color: '#999' }}>
                      {item.duration_ms}ms
                    </span>
                  )}
                </div>
                {item.error && (
                  <div style={{ marginTop: 8, color: '#cf1322', fontSize: 12 }}>
                    <CloseCircleOutlined /> {item.error}
                  </div>
                )}
                {item.status === 'success' && Object.keys(item.output).length > 0 && (
                  <pre
                    style={{
                      marginTop: 8,
                      padding: 8,
                      background: '#fafafa',
                      borderRadius: 4,
                      fontSize: 11,
                      maxHeight: 160,
                      overflow: 'auto',
                    }}
                  >
                    {JSON.stringify(item.output, null, 2)}
                  </pre>
                )}
              </div>
            </List.Item>
          )}
        />
        {finalResult && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>最终 outputs</div>
            <pre
              style={{
                padding: 12,
                background: '#f6ffed',
                borderRadius: 4,
                fontSize: 12,
                maxHeight: 240,
                overflow: 'auto',
              }}
            >
              {JSON.stringify(finalResult, null, 2)}
            </pre>
          </div>
        )}
      </Drawer>
    </>
  )
}
