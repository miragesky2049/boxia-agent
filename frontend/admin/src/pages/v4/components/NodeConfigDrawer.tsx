import { PlusOutlined, CloseOutlined } from '@ant-design/icons'
import { App, Button, Drawer, Empty, Form, Input, InputNumber, Select, Slider, Space } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { listAvailableModels } from '../../../api/v4'
import {
  getUpstreamNodeIds,
  listOutputFields,
  useV4AppStore,
  type V4NodeType,
} from '../store/appStore'

interface Props {
  open: boolean
  onClose: () => void
}

const TYPE_LABEL: Record<V4NodeType, string> = {
  start: '开始节点',
  llm: 'LLM 节点',
  end: '结束节点',
  branch: '条件分支',
  tool: '工具节点',
  template: '模板节点',
  http: 'HTTP 节点',
}

interface ModelOption {
  model_id: string
  display_name: string
  provider_name: string
}

function useAvailableModels(): { data: ModelOption[] | null; loading: boolean } {
  const [data, setData] = useState<ModelOption[] | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    setLoading(true)
    listAvailableModels()
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])
  return { data, loading }
}

function ModelSelect({
  value,
  onChange,
}: {
  value?: string
  onChange?: (v: string) => void
}) {
  const { data, loading } = useAvailableModels()
  return (
    <Select
      loading={loading}
      placeholder="选择模型"
      value={value}
      onChange={onChange}
      options={(data ?? []).map((m) => ({
        value: m.model_id,
        label: `${m.display_name || m.model_id}（${m.provider_name}）`,
      }))}
    />
  )
}

/** 根据当前选中节点，列出上游节点可插入的变量提示列表 */
function useUpstreamVariableHints(nodeId: string | null) {
  const nodes = useV4AppStore((s) => s.nodes)
  const edges = useV4AppStore((s) => s.edges)
  return useMemo(() => {
    if (!nodeId) return []
    const upstreamIds = getUpstreamNodeIds(edges, nodeId)
    return upstreamIds.flatMap((uid) => {
      const unode = nodes.find((n) => n.id === uid)
      if (!unode) return []
      return listOutputFields(unode.data.nodeType).map((field) => ({
        label: `{{#${uid}.${field}#}}`,
        value: `{{#${uid}.${field}#}}`,
      }))
    })
  }, [nodeId, nodes, edges])
}

/** 带变量插值提示的 TextArea：输入 {{# 时弹出上游字段列表 */
function PromptTextArea({
  value,
  onChange,
  placeholder,
  nodeId,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  nodeId: string
}) {
  const hints = useUpstreamVariableHints(nodeId)
  const [showHints, setShowHints] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const v = e.target.value
    onChange(v)
    // 光标前两个字符是 {{# 时弹出提示
    const cursorPos = e.target.selectionStart ?? v.length
    const before = v.slice(Math.max(0, cursorPos - 3), cursorPos)
    setShowHints(before.endsWith('{{#'))
  }

  const insertHint = (hint: string) => {
    // 把最后的 {{# 替换为 hint
    const idx = value.lastIndexOf('{{#')
    if (idx >= 0) {
      onChange(value.slice(0, idx) + hint)
    } else {
      onChange(value + hint)
    }
    setShowHints(false)
  }

  return (
    <div style={{ position: 'relative' }}>
      <Input.TextArea
        rows={4}
        value={value}
        onChange={handleChange}
        placeholder={placeholder}
      />
      {showHints && hints.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: 4,
            background: '#fff',
            border: '1px solid #d9d9d9',
            borderRadius: 4,
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
            zIndex: 1000,
            maxHeight: 200,
            overflow: 'auto',
          }}
        >
          {hints.map((h) => (
            <div
              key={h.value}
              onClick={() => insertHint(h.value)}
              style={{
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: 12,
                fontFamily: 'monospace',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#f5f5f5')}
              onMouseLeave={(e) => (e.currentTarget.style.background = '#fff')}
            >
              {h.label}
            </div>
          ))}
        </div>
      )}
      {showHints && hints.length === 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: 4,
            padding: '6px 10px',
            background: '#fff',
            border: '1px solid #d9d9d9',
            borderRadius: 4,
            fontSize: 12,
            color: '#999',
          }}
        >
          暂无上游节点输出字段
        </div>
      )}
    </div>
  )
}

/** start 节点输入变量动态列表 */
function InputVariablesEditor() {
  const variables: { name: string; type: string; required: boolean; default: string }[] =
    Form.useWatch('inputs') ?? []

  return (
    <Form.List name="inputs">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name, ...restField }) => (
            <Space.Compact key={key} style={{ display: 'flex', marginBottom: 8 }} block>
              <Form.Item
                {...restField}
                name={[name, 'name']}
                rules={[{ required: true, message: '变量名必填' }]}
                style={{ flex: 2 }}
              >
                <Input placeholder="变量名，如 query" />
              </Form.Item>
              <Form.Item {...restField} name={[name, 'type']} style={{ flex: 1 }}>
                <Select
                  options={['string', 'number', 'boolean', 'json'].map((t) => ({
                    value: t,
                    label: t,
                  }))}
                />
              </Form.Item>
              <Form.Item {...restField} name={[name, 'required']} valuePropName="checked" style={{ flex: 0.5 }}>
                <Select
                  options={[
                    { value: true, label: '必填' },
                    { value: false, label: '可选' },
                  ]}
                />
              </Form.Item>
              <Form.Item {...restField} name={[name, 'default']} style={{ flex: 1.5 }}>
                <Input placeholder="默认值" />
              </Form.Item>
              <Button
                type="text"
                danger
                icon={<CloseOutlined />}
                onClick={() => remove(name)}
              />
            </Space.Compact>
          ))}
          <Button
            type="dashed"
            onClick={() => add({ name: '', type: 'string', required: true, default: '' })}
            block
            icon={<PlusOutlined />}
          >
            添加输入变量
          </Button>
          {variables.length === 0 && (
            <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
              未定义输入变量，试运行时可直接传 JSON
            </div>
          )}
        </>
      )}
    </Form.List>
  )
}

/** end 节点输出变量动态列表 */
function OutputVariablesEditor() {
  return (
    <Form.List name="outputs">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name, ...restField }) => (
            <Space.Compact key={key} style={{ display: 'flex', marginBottom: 8 }} block>
              <Form.Item
                {...restField}
                name={[name, 'name']}
                rules={[{ required: true, message: '输出名必填' }]}
                style={{ flex: 1.5 }}
              >
                <Input placeholder="输出名，如 answer" />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'value']}
                rules={[{ required: true, message: '取值表达式必填' }]}
                style={{ flex: 3 }}
              >
                <Input placeholder={'{{#llm_1.output#}}'} />
              </Form.Item>
              <Button
                type="text"
                danger
                icon={<CloseOutlined />}
                onClick={() => remove(name)}
              />
            </Space.Compact>
          ))}
          <Button
            type="dashed"
            onClick={() => add({ name: '', value: '' })}
            block
            icon={<PlusOutlined />}
          >
            添加输出变量
          </Button>
          <div style={{ marginTop: 8, fontSize: 12, color: '#999' }}>
            留空则自动汇聚最后一个 LLM 节点的输出
          </div>
        </>
      )}
    </Form.List>
  )
}

export function NodeConfigDrawer({ open, onClose }: Props) {
  const { message } = App.useApp()
  const selectedNodeId = useV4AppStore((s) => s.selectedNodeId)
  const nodes = useV4AppStore((s) => s.nodes)
  const updateNodeConfig = useV4AppStore((s) => s.updateNodeConfig)
  const removeNode = useV4AppStore((s) => s.removeNode)

  const node = nodes.find((n) => n.id === selectedNodeId)
  const [form] = Form.useForm()
  // 统一在顶层调用 watch，避免条件分支里调用 hook 导致 hook 顺序变化
  const watchedSystemPrompt = (Form.useWatch('system_prompt', form) as string) ?? ''
  const watchedTemplate = (Form.useWatch('template', form) as string) ?? ''

  useEffect(() => {
    if (node) {
      form.setFieldsValue(node.data.config)
    }
  }, [node, form])

  const handleSave = async () => {
    if (!node) return
    try {
      const values = await form.validateFields()
      updateNodeConfig(node.id, values)
      message.success('配置已应用（点击工具栏"保存"提交到后端）')
    } catch {
      // 校验失败，antd 已提示
    }
  }

  const handleDelete = () => {
    if (!node) return
    removeNode(node.id)
    onClose()
    message.success('节点已删除')
  }

  const renderConfigForm = () => {
    if (!node) return <Empty description="未选择节点" />
    const type = node.data.nodeType

    switch (type) {
      case 'start':
        return (
          <>
            <div style={{ marginBottom: 8, fontSize: 13, color: '#595959' }}>
              输入变量：定义 start 节点接受的字段
            </div>
            <InputVariablesEditor />
          </>
        )
      case 'end':
        return (
          <>
            <div style={{ marginBottom: 8, fontSize: 13, color: '#595959' }}>
              输出变量：定义 end 节点最终返回的字段
            </div>
            <OutputVariablesEditor />
          </>
        )
      case 'llm':
        return (
          <>
            <Form.Item
              label="模型"
              name="model_id"
              rules={[{ required: true, message: '请选择模型' }]}
            >
              <ModelSelect />
            </Form.Item>
            <Form.Item label="系统提示词" name="system_prompt">
              <PromptTextArea
                value={watchedSystemPrompt}
                onChange={(v) => form.setFieldValue('system_prompt', v)}
                placeholder="输入 {{# 可插入上游节点输出"
                nodeId={node.id}
              />
            </Form.Item>
            <Form.Item label="温度" name="temperature">
              <Slider min={0} max={2} step={0.1} marks={{ 0: '0', 1: '1', 2: '2' }} />
            </Form.Item>
            <Form.Item label="最大 tokens" name="max_tokens">
              <InputNumber min={64} max={8192} style={{ width: '100%' }} />
            </Form.Item>
          </>
        )
      case 'branch':
        return (
          <>
            <Form.Item label="条件（JSON 数组）" name="conditions">
              <Input.TextArea
                rows={3}
                placeholder='[{"field":"input.score","operator":"gt","value":80}]'
              />
            </Form.Item>
            <Form.Item label="true 分支目标节点 ID" name={['routes', 'true']}>
              <Input placeholder="例如 llm_2" />
            </Form.Item>
            <Form.Item label="false 分支目标节点 ID" name={['routes', 'false']}>
              <Input placeholder="例如 llm_3" />
            </Form.Item>
          </>
        )
      case 'tool':
        return (
          <>
            <Form.Item label="工具资源 ID" name="resource_id">
              <Input placeholder="资源 UUID" />
            </Form.Item>
            <Form.Item label="参数 JSON" name="params">
              <Input.TextArea rows={4} placeholder='{"key": "{{#input.query#}}"}' />
            </Form.Item>
          </>
        )
      case 'template':
        return (
          <Form.Item label="模板内容" name="template">
            <PromptTextArea
              value={watchedTemplate}
              onChange={(v) => form.setFieldValue('template', v)}
              placeholder="输入 {{# 可插入上游节点输出"
              nodeId={node.id}
            />
          </Form.Item>
        )
      case 'http':
        return (
          <>
            <Form.Item label="URL" name="url" rules={[{ required: true }]}>
              <Input placeholder="https://api.example.com/..." />
            </Form.Item>
            <Form.Item label="方法" name="method">
              <Select
                options={['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].map((m) => ({
                  value: m,
                  label: m,
                }))}
              />
            </Form.Item>
            <Form.Item label="请求体" name="body">
              <Input.TextArea rows={4} />
            </Form.Item>
          </>
        )
    }
  }

  return (
    <Drawer
      title={node ? TYPE_LABEL[node.data.nodeType] : '节点配置'}
      width={420}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button danger onClick={handleDelete} disabled={!node}>
            删除节点
          </Button>
          <Button type="primary" onClick={handleSave} disabled={!node}>
            应用配置
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical">
        {renderConfigForm()}
      </Form>
    </Drawer>
  )
}
