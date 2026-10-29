import { LoadingOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { App, Button, Form, Input, InputNumber, Modal, Space, Switch, Tabs } from 'antd'
import { useEffect, useMemo, useState } from 'react'

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

interface InputVar {
  name: string
  type: string
  required: boolean
  default: string
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
  const [inputs, setInputs] = useState<Record<string, unknown>>({})
  const [inputsText, setInputsText] = useState('{}')
  const [useJsonMode, setUseJsonMode] = useState(false)
  const [running, setRunning] = useState(false)
  const [states, setStates] = useState<Record<string, DebugNodeState>>({})
  const [form] = Form.useForm()

  // 从 graph 中提取 start 节点的输入变量定义
  const startInputs = useMemo<InputVar[]>(() => {
    const startNode = graph.nodes.find((n) => n.node_type === 'start')
    if (!startNode?.config) return []
    const inputs = (startNode.config as { inputs?: InputVar[] }).inputs
    return inputs ?? []
  }, [graph])

  // 打开时初始化表单默认值
  useEffect(() => {
    if (open && startInputs.length > 0) {
      const defaults: Record<string, unknown> = {}
      startInputs.forEach((v) => {
        if (v.default) {
          defaults[v.name] = v.type === 'number' ? Number(v.default) : v.default
        } else {
          defaults[v.name] = v.type === 'number' ? 0 : v.type === 'boolean' ? false : ''
        }
      })
      setInputs(defaults)
      form.setFieldsValue(defaults)
    }
  }, [open, startInputs, form])

  useEffect(() => {
    onRunningChange(running)
  }, [running, onRunningChange])

  useEffect(() => {
    onNodeStateChange(states)
  }, [states, onNodeStateChange])

  const handleRun = async () => {
    let runInputs: Record<string, unknown>
    if (useJsonMode) {
      try {
        runInputs = JSON.parse(inputsText || '{}')
      } catch {
        message.error('入参必须是合法 JSON')
        return
      }
    } else {
      try {
        runInputs = await form.validateFields()
      } catch {
        return
      }
    }

    setRunning(true)
    setStates({})
    onFinalResult(null)
    try {
      await debugRunAppStream({ graph, inputs: runInputs }, (evt) => {
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

  // 根据变量类型渲染输入控件
  const renderInput = (v: InputVar) => {
    const rules = v.required ? [{ required: true, message: `${v.name} 必填` }] : []
    switch (v.type) {
      case 'number':
        return <InputNumber style={{ width: '100%' }} placeholder={v.default || v.name} />
      case 'boolean':
        return <Switch checkedChildren="true" unCheckedChildren="false" />
      case 'json':
        return <Input.TextArea rows={3} style={{ fontFamily: 'monospace', fontSize: 12 }} placeholder='{"key": "value"}' />
      default:
        return <Input placeholder={v.default || v.name} />
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
      width={640}
      destroyOnHidden
    >
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 13, color: '#595959' }}>
            {startInputs.length > 0 ? '入参（按开始节点定义自动生成表单）' : '入参 JSON'}
          </span>
          {startInputs.length > 0 && (
            <div style={{ fontSize: 12 }}>
              <span style={{ marginRight: 8, color: '#8c8c8c' }}>JSON 模式</span>
              <Switch checked={useJsonMode} onChange={setUseJsonMode} size="small" />
            </div>
          )}
        </div>

        {startInputs.length === 0 || useJsonMode ? (
          <Input.TextArea
            value={inputsText}
            onChange={(e) => setInputsText(e.target.value)}
            rows={6}
            style={{ fontFamily: 'monospace', fontSize: 12 }}
            placeholder='{ "query": "你好" }'
            disabled={running}
          />
        ) : (
          <Form form={form} layout="vertical" disabled={running}>
            {startInputs.map((v) => (
              <Form.Item
                key={v.name}
                name={v.name}
                label={
                  <Space size={4}>
                    <span>{v.name}</span>
                    <span style={{ fontSize: 11, color: '#8c8c8c' }}>({v.type})</span>
                    {v.required && <span style={{ color: '#ff4d4f' }}>*</span>}
                  </Space>
                }
                rules={v.required ? [{ required: true, message: `${v.name} 必填` }] : []}
              >
                {renderInput(v)}
              </Form.Item>
            ))}
          </Form>
        )}
      </div>
    </Modal>
  )
}
