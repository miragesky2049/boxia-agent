import { PlusOutlined, CloseOutlined, BulbOutlined } from '@ant-design/icons'
import { App, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Select, Slider, Space, Switch, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import {
  listApps,
  listAvailableModels,
  listResources,
  optimizePrompt,
  type PromptOptimizeResult,
  type Resource,
} from '../../../api/apps'
import {
  getUpstreamNodeIds,
  listOutputFields,
  useAppStore,
  type NodeType,
} from '../store/appStore'

interface Props {
  open: boolean
  onClose: () => void
}

const TYPE_LABEL: Record<NodeType, string> = {
  start: '开始节点',
  llm: 'LLM 节点',
  end: '结束节点',
  branch: '条件分支',
  tool: '工具节点',
  template: '模板节点',
  http: 'HTTP 节点',
  retrieval: '检索节点',
  human_task: '人审节点',
  subgraph: '子图节点',
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

/** 工具资源下拉：tool 节点绑定工具用 */
function useToolResources(): { data: Resource[] | null; loading: boolean } {
  const [data, setData] = useState<Resource[] | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    setLoading(true)
    listResources({ type: 'tool' })
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])
  return { data, loading }
}

function ToolResourceSelect({
  value,
  onChange,
}: {
  value?: string
  onChange?: (v: string) => void
}) {
  const { data, loading } = useToolResources()
  return (
    <Select
      loading={loading}
      allowClear
      showSearch
      placeholder="选择已注册的工具资源"
      value={value}
      onChange={onChange}
      optionFilterProp="label"
      options={(data ?? [])
        .filter((r) => r.is_enabled && !r.is_deprecated)
        .map((r) => ({
          value: r.id,
          label: `${r.name}（${r.id.slice(0, 8)}…）`,
        }))}
    />
  )
}

/** 知识库资源下拉：retrieval 节点绑定知识库用 */
function useKnowledgeResources(): { data: Resource[] | null; loading: boolean } {
  const [data, setData] = useState<Resource[] | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    setLoading(true)
    listResources({ type: 'knowledge' })
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])
  return { data, loading }
}

function KnowledgeResourceSelect({
  value,
  onChange,
}: {
  value?: string
  onChange?: (v: string) => void
}) {
  const { data, loading } = useKnowledgeResources()
  return (
    <Select
      loading={loading}
      allowClear
      showSearch
      placeholder="选择已注册的知识库"
      value={value}
      onChange={onChange}
      optionFilterProp="label"
      options={(data ?? [])
        .filter((r) => r.is_enabled && !r.is_deprecated)
        .map((r) => ({
          value: r.id,
          label: `${r.name}（${r.id.slice(0, 8)}…）`,
        }))}
    />
  )
}

/** 平台应用下拉：subgraph 节点选择嵌套应用用 */
function usePlatformApps(): { data: { id: string; name: string }[] | null; loading: boolean } {
  const [data, setData] = useState<{ id: string; name: string }[] | null>(null)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    setLoading(true)
    listApps({ owner_type: 'platform' })
      .then((apps) => setData(apps.map((a) => ({ id: a.id, name: a.name }))))
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])
  return { data, loading }
}

function SubgraphAppSelect({
  value,
  onChange,
}: {
  value?: string
  onChange?: (v: string) => void
}) {
  const { data, loading } = usePlatformApps()
  return (
    <Select
      loading={loading}
      allowClear
      showSearch
      placeholder="选择要嵌套调用的平台应用"
      value={value}
      onChange={onChange}
      optionFilterProp="label"
      options={(data ?? []).map((a) => ({
        value: a.id,
        label: `${a.name}（${a.id.slice(0, 8)}…）`,
      }))}
    />
  )
}

/** 根据当前选中节点，列出上游节点可插入的变量提示列表 */
function useUpstreamVariableHints(nodeId: string | null) {
  const nodes = useAppStore((s) => s.nodes)
  const edges = useAppStore((s) => s.edges)
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
                style={{ flex: 2.2, marginBottom: 0 }}
              >
                <Input placeholder="变量名，如 query" />
              </Form.Item>
              <Form.Item {...restField} name={[name, 'type']} style={{ flex: 1.3, marginBottom: 0 }}>
                <Select
                  options={['string', 'number', 'boolean', 'json'].map((t) => ({
                    value: t,
                    label: t,
                  }))}
                />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'required']}
                valuePropName="checked"
                style={{ flex: 1.1, marginBottom: 0 }}
              >
                <Switch checkedChildren="必填" unCheckedChildren="选填" />
              </Form.Item>
              <Form.Item {...restField} name={[name, 'default']} style={{ flex: 1.8, marginBottom: 0 }}>
                <Input placeholder="默认值（选填）" />
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
                style={{ flex: 1.5, marginBottom: 0 }}
              >
                <Input placeholder="输出名，如 answer" />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'value']}
                rules={[{ required: true, message: '取值表达式必填' }]}
                style={{ flex: 3, marginBottom: 0 }}
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

/** 把表单里的 JSON 文本字段解析为对象/数组，与后端 config 结构对齐 */
function parseJsonField(raw: unknown, label: string): unknown {
  if (raw === undefined || raw === null || raw === '') return undefined
  if (typeof raw !== 'string') return raw
  try {
    return JSON.parse(raw)
  } catch {
    throw new Error(`${label}不是合法 JSON，请检查后重试`)
  }
}

function normalizeConfig(nodeType: NodeType, values: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = { ...values }
  if (nodeType === 'branch') {
    const conditions = parseJsonField(result.conditions, '条件')
    if (conditions !== undefined) result.conditions = conditions
    else delete result.conditions
  }
  if (nodeType === 'tool') {
    const params = parseJsonField(result.params, '参数 JSON')
    if (params !== undefined) result.params = params
    else result.params = {}
  }
  if (nodeType === 'http') {
    const body = parseJsonField(result.body, '请求体')
    if (body !== undefined) result.body = body
    else delete result.body
  }
  if (nodeType === 'subgraph') {
    const mapping = parseJsonField(result.input_mapping, '入参映射')
    if (mapping !== undefined) result.input_mapping = mapping
    else result.input_mapping = {}
  }
  return result
}

export function NodeConfigDrawer({ open, onClose }: Props) {
  const { message } = App.useApp()
  const selectedNodeId = useAppStore((s) => s.selectedNodeId)
  const nodes = useAppStore((s) => s.nodes)
  const updateNodeConfig = useAppStore((s) => s.updateNodeConfig)
  const removeNode = useAppStore((s) => s.removeNode)

  const node = nodes.find((n) => n.id === selectedNodeId)
  const [form] = Form.useForm()
  // 统一在顶层调用 watch，避免条件分支里调用 hook 导致 hook 顺序变化
  const watchedSystemPrompt = (Form.useWatch('system_prompt', form) as string) ?? ''
  const watchedTemplate = (Form.useWatch('template', form) as string) ?? ''

  // AI prompt 优化 Modal
  const [optimizeOpen, setOptimizeOpen] = useState(false)
  const [optimizeLoading, setOptimizeLoading] = useState(false)
  const [taskDescription, setTaskDescription] = useState('')
  const [optimizeResult, setOptimizeResult] = useState<PromptOptimizeResult | null>(null)

  const handleOptimizeClick = () => {
    setOptimizeResult(null)
    setTaskDescription('')
    setOptimizeOpen(true)
  }

  const handleOptimizeRun = async () => {
    const modelId = form.getFieldValue('model_id') as string | undefined
    const currentPrompt = (form.getFieldValue('system_prompt') as string | undefined) ?? ''
    if (!modelId) {
      message.warning('请先在上方选择模型')
      return
    }
    if (!currentPrompt.trim()) {
      message.warning('请先填写当前 system prompt')
      return
    }
    setOptimizeLoading(true)
    setOptimizeResult(null)
    try {
      const result = await optimizePrompt({
        model_id: modelId,
        current_prompt: currentPrompt,
        task_description: taskDescription,
      })
      setOptimizeResult(result)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '优化失败')
    } finally {
      setOptimizeLoading(false)
    }
  }

  const handleOptimizeAccept = () => {
    if (!optimizeResult) return
    form.setFieldValue('system_prompt', optimizeResult.optimized_prompt)
    message.success('已采纳优化后的 prompt，记得点"应用配置"')
    setOptimizeOpen(false)
    setOptimizeResult(null)
  }

  useEffect(() => {
    if (node) {
      const cfg: Record<string, unknown> = { ...node.data.config }
      // 后端存的是对象/数组，TextArea 需要 JSON 字符串才能正常回显
      for (const key of ['conditions', 'params', 'body', 'input_mapping']) {
        const v = cfg[key]
        if (v !== undefined && v !== null && typeof v !== 'string') {
          cfg[key] = JSON.stringify(v, null, 2)
        }
      }
      form.setFieldsValue(cfg)
    }
  }, [node, form])

  const handleSave = async () => {
    if (!node) return
    try {
      const values = await form.validateFields()
      const normalized = normalizeConfig(node.data.nodeType, values)
      updateNodeConfig(node.id, normalized)
      message.success('配置已应用（点击工具栏"保存"提交到后端）')
    } catch (error) {
      if (error instanceof Error) {
        message.error(error.message)
      }
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
            <Form.Item
              label={
                <Space size="small">
                  <span>系统提示词</span>
                  <Button
                    size="small"
                    type="link"
                    icon={<BulbOutlined />}
                    onClick={handleOptimizeClick}
                  >
                    AI 优化
                  </Button>
                </Space>
              }
              name="system_prompt"
            >
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
      case 'branch': {
        // 分支目标节点：排除开始节点（不能作为终点）和自身
        const routeOptions = nodes
          .filter((n) => n.id !== node.id && n.data.nodeType !== 'start')
          .map((n) => ({
            value: n.id,
            label: `${n.id}（${TYPE_LABEL[n.data.nodeType]}）`,
          }))
        return (
          <>
            <Form.Item
              label="条件（JSON 数组，全部满足走 true）"
              name="conditions"
              tooltip="数组内条件为 AND 关系；字段从 start 节点入参中取值，支持 a.b 嵌套"
            >
              <Input.TextArea
                rows={4}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
                placeholder='[{"field":"score","operator":"gt","value":80}]'
              />
            </Form.Item>
            <div
              style={{ margin: '-8px 0 16px', padding: '8px 12px', background: '#fafafa', borderRadius: 4, fontSize: 12, color: '#595959', lineHeight: 1.8 }}
            >
              <div>field：入参字段名，如 score（从 start 入参取值，不要带 input. 前缀）</div>
              <div>operator：eq 等于 / ne 不等于 / gt 大于 / contains 包含</div>
              <div>value：比较值；字符串用双引号，数字直接写</div>
            </div>
            <Form.Item label="true 分支目标节点" name={['routes', 'true']}>
              <Select
                allowClear
                showSearch
                placeholder="选择条件满足时流向的节点"
                options={routeOptions}
              />
            </Form.Item>
            <Form.Item label="false 分支目标节点" name={['routes', 'false']}>
              <Select
                allowClear
                showSearch
                placeholder="选择条件不满足时流向的节点"
                options={routeOptions}
              />
            </Form.Item>
            <div style={{ marginTop: -8, fontSize: 12, color: '#fa8c16' }}>
              注意：选完目标节点后，还需从本节点拉线到对应目标节点，试运行才会生效。
            </div>
          </>
        )
      }
      case 'tool':
        return (
          <>
            <Form.Item label="工具资源" name="resource_id">
              <ToolResourceSelect />
            </Form.Item>
            <Form.Item
              label="参数 JSON"
              name="params"
              tooltip="调用工具时传入的参数对象，支持 {{#input.字段#}} 占位符"
            >
              <Input.TextArea
                rows={4}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
                placeholder='{"key": "{{#input.query#}}"}'
              />
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
      case 'retrieval':
        return (
          <>
            <Form.Item label="知识库" name="knowledge_base_id">
              <KnowledgeResourceSelect />
            </Form.Item>
            <Form.Item label="查询字段" name="query_field">
              <Input placeholder="从 input 取哪个字段作为 query（默认 query）" />
            </Form.Item>
            <Form.Item label="Top K" name="top_k">
              <InputNumber min={1} max={50} style={{ width: '100%' }} />
            </Form.Item>
          </>
        )
      case 'human_task':
        return (
          <>
            <Form.Item label="指派角色" name="assignee_role">
              <Input placeholder="如 reviewer / approver" />
            </Form.Item>
            <Form.Item label="审批说明" name="instructions">
              <Input.TextArea rows={4} placeholder="告诉审批人需要做什么" />
            </Form.Item>
          </>
        )
      case 'subgraph':
        return (
          <>
            <Form.Item label="子图应用" name="application_id" rules={[{ required: true, message: '请选择子图应用' }]}>
              <SubgraphAppSelect />
            </Form.Item>
            <Form.Item
              label="入参映射（JSON）"
              name="input_mapping"
              tooltip={'父 state 字段 -> 子图 input 字段，如 {"query": "query"}'}
            >
              <Input.TextArea
                rows={3}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
                placeholder='{"query": "query"}'
              />
            </Form.Item>
          </>
        )
    }
  }

  return (
    <Drawer
      title={node ? TYPE_LABEL[node.data.nodeType] : '节点配置'}
      width={560}
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

      <Modal
        title="AI 优化 system prompt"
        open={optimizeOpen}
        onCancel={() => {
          setOptimizeOpen(false)
          setOptimizeResult(null)
        }}
        destroyOnClose
        width={640}
        footer={
          optimizeResult ? (
            <Space>
              <Button
                onClick={() => {
                  setOptimizeOpen(false)
                  setOptimizeResult(null)
                }}
              >
                取消
              </Button>
              <Button type="primary" onClick={handleOptimizeAccept}>
                采纳优化结果
              </Button>
            </Space>
          ) : (
            <Space>
              <Button onClick={() => setOptimizeOpen(false)}>取消</Button>
              <Button
                type="primary"
                loading={optimizeLoading}
                onClick={handleOptimizeRun}
              >
                开始优化
              </Button>
            </Space>
          )
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              当前 system prompt：
            </Typography.Text>
            <Input.TextArea
              value={watchedSystemPrompt}
              readOnly
              rows={5}
              style={{ marginTop: 4, fontSize: 12, background: '#fafafa' }}
            />
          </div>

          {!optimizeResult && (
            <div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                任务描述（可选，帮助 AI 理解业务意图）：
              </Typography.Text>
              <Input.TextArea
                value={taskDescription}
                onChange={(e) => setTaskDescription(e.target.value)}
                rows={3}
                placeholder='例如："让回答更简洁，不超过 100 字"、"主要面向售后工单场景"'
                style={{ marginTop: 4 }}
              />
            </div>
          )}

          {optimizeResult && (
            <>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  优化后的 prompt：
                </Typography.Text>
                <Input.TextArea
                  value={optimizeResult.optimized_prompt}
                  readOnly
                  rows={8}
                  style={{ marginTop: 4, fontSize: 12, background: '#f6ffed' }}
                />
              </div>
              {optimizeResult.suggestions.length > 0 && (
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    改动建议：
                  </Typography.Text>
                  <ul style={{ margin: '4px 0 0 20px', padding: 0 }}>
                    {optimizeResult.suggestions.map((s, i) => (
                      <li key={i} style={{ fontSize: 12, color: '#595959' }}>
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </Space>
      </Modal>
    </Drawer>
  )
}
