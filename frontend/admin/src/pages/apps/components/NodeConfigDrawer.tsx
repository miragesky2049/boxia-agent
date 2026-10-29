import { PlusOutlined, CloseOutlined, BulbOutlined, CopyOutlined } from '@ant-design/icons'
import { App, Button, Drawer, Empty, Form, Input, InputNumber, Modal, Select, Slider, Space, Switch, Tag, Typography, Collapse } from 'antd'
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

const VAR_TYPE_META: Record<string, { label: string; color: string }> = {
  string: { label: 'str', color: 'blue' },
  number: { label: 'num', color: 'green' },
  boolean: { label: 'bool', color: 'orange' },
  json: { label: 'json', color: 'purple' },
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
                  optionLabelProp="label"
                  options={Object.entries(VAR_TYPE_META).map(([value, meta]) => ({
                    value,
                    label: meta.label,
                  }))}
                  optionRender={(opt) => {
                    const meta = VAR_TYPE_META[opt.value as string]
                    return (
                      <Space size={4}>
                        <Tag color={meta?.color} style={{ marginInlineEnd: 0 }}>{meta?.label}</Tag>
                        <span style={{ fontSize: 12, color: '#8c8c8c' }}>{opt.value}</span>
                      </Space>
                    )
                  }}
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
              <Form.Item {...restField} name={[name, 'default']} style={{ flex: 1.6, marginBottom: 0 }}>
                <Input placeholder="默认值（选填）" />
              </Form.Item>
              <Button
                type="text"
                icon={<CopyOutlined />}
                title="复制此行"
                onClick={() => {
                  const current = variables[name]
                  if (!current) return
                  add({ ...current, name: `${current.name}_copy` }, name + 1)
                }}
              />
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

/** 输出值输入框 + 弹窗选择上游变量 */
function OutputValueInput({
  value,
  onChange,
  nodeId,
}: {
  value?: string
  onChange?: (v: string) => void
  nodeId: string
}) {
  const hints = useUpstreamVariableHints(nodeId)
  const [pickerOpen, setPickerOpen] = useState(false)
  return (
    <>
      <Space.Compact style={{ display: 'flex', width: '100%' }}>
        <Input
          value={value}
          onChange={(e) => onChange?.(e.target.value)}
          placeholder={'{{#llm_1.output#}}'}
          style={{ flex: 1, fontFamily: 'monospace', fontSize: 12 }}
        />
        <Button onClick={() => setPickerOpen(true)}>选择变量</Button>
      </Space.Compact>
      <Modal
        title="选择上游变量"
        open={pickerOpen}
        onCancel={() => setPickerOpen(false)}
        onOk={() => setPickerOpen(false)}
        okText="确定"
        width={520}
      >
        {hints.length === 0 ? (
          <Empty description="暂无上游节点输出字段" />
        ) : (
          <div style={{ maxHeight: 360, overflow: 'auto' }}>
            {hints.map((h) => (
              <div
                key={h.value}
                onClick={() => {
                  onChange?.(h.value)
                  setPickerOpen(false)
                }}
                style={{
                  padding: '8px 10px',
                  cursor: 'pointer',
                  fontFamily: 'monospace',
                  fontSize: 12,
                  borderBottom: '1px solid #f0f0f0',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = '#f5f5f5')}
                onMouseLeave={(e) => (e.currentTarget.style.background = '#fff')}
              >
                {h.label}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  )
}

/** end 节点输出变量动态列表 */
function OutputVariablesEditor({ nodeId }: { nodeId: string }) {
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
                <OutputValueInput nodeId={nodeId} />
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

/** 通用 key-value 动态编辑器：替代裸 JSON TextArea（参考 coze/dify 的参数表单） */
function KeyValueEditor({
  name,
  keyPlaceholder,
  valuePlaceholder,
  addText,
}: {
  name: string
  keyPlaceholder?: string
  valuePlaceholder?: string
  addText?: string
}) {
  return (
    <Form.List name={name}>
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name, ...restField }) => (
            <Space.Compact key={key} style={{ display: 'flex', marginBottom: 8 }} block>
              <Form.Item
                {...restField}
                name={[name, 'key']}
                rules={[{ required: true, message: '键名必填' }]}
                style={{ flex: 1.5, marginBottom: 0 }}
              >
                <Input placeholder={keyPlaceholder ?? '键名'} />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'value']}
                style={{ flex: 2.5, marginBottom: 0, marginLeft: 8 }}
              >
                <Input placeholder={valuePlaceholder ?? '值，支持 {{#input.query#}}'} />
              </Form.Item>
              <Button
                type="text"
                danger
                icon={<CloseOutlined />}
                style={{ marginLeft: 8 }}
                onClick={() => remove(name)}
              />
            </Space.Compact>
          ))}
          <Button
            type="dashed"
            onClick={() => add({ key: '', value: '' })}
            block
            icon={<PlusOutlined />}
          >
            {addText ?? '添加一行'}
          </Button>
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

/** 把 [{key, value}] 数组转回对象 */
function kvArrayToObject(arr: unknown): Record<string, string> {
  if (!Array.isArray(arr)) return {}
  const obj: Record<string, string> = {}
  for (const item of arr) {
    if (item && typeof item === 'object' && 'key' in item && item.key) {
      obj[(item as { key: string }).key] = String((item as { value?: unknown }).value ?? '')
    }
  }
  return obj
}

/** 把对象转成 [{key, value}] 数组供 Form.List 使用 */
function objectToKvArray(obj: unknown): { key: string; value: string }[] {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return []
  return Object.entries(obj as Record<string, unknown>).map(([key, value]) => ({
    key,
    value: String(value ?? ''),
  }))
}

function normalizeConfig(nodeType: NodeType, values: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = { ...values }
  if (nodeType === 'tool') {
    result.params = kvArrayToObject(result.params)
  }
  if (nodeType === 'http') {
    result.headers = kvArrayToObject(result.headers)
    result.params = kvArrayToObject(result.params)
    const body = parseJsonField(result.body, '请求体')
    if (body !== undefined) result.body = body
    else delete result.body
  }
  if (nodeType === 'subgraph') {
    result.input_mapping = kvArrayToObject(result.input_mapping)
  }
  return result
}

const BRANCH_OPERATORS: { value: string; label: string }[] = [
  { value: 'eq', label: '等于 (==)' },
  { value: 'ne', label: '不等于 (!=)' },
  { value: 'gt', label: '大于 (>)' },
  { value: 'contains', label: '包含 (contains)' },
]

/** 通用重试配置：失败时重试开关 + 最大重试次数（参考 dify LLM/HTTP 节点的"失败时重试"） */
function RetryConfigFields() {
  const retryEnabled = (Form.useWatch('retry_enabled') as boolean) ?? false
  return (
    <>
      <Form.Item label="失败时重试" name="retry_enabled" valuePropName="checked">
        <Switch checkedChildren="开启" unCheckedChildren="关闭" />
      </Form.Item>
      {retryEnabled && (
        <Form.Item label="最大重试次数" name="max_retries">
          <InputNumber min={1} max={10} style={{ width: '100%' }} addonAfter="次" />
        </Form.Item>
      )}
    </>
  )
}

/** 分支条件可视化构建器：参考 coze IF 节点，行内编辑字段/操作符/值 */
function BranchConditionsEditor({
  startInputs,
}: {
  startInputs: { name: string; type: string }[]
}) {
  const fieldOptions = startInputs.map((v) => ({
    value: v.name,
    label: `${v.name}（${VAR_TYPE_META[v.type]?.label ?? v.type}）`,
  }))
  return (
    <Form.List name="conditions">
      {(fields, { add, remove }) => (
        <>
          <div
            style={{
              display: 'flex',
              fontSize: 12,
              color: '#8c8c8c',
              marginBottom: 4,
              padding: '0 4px',
            }}
          >
            <span style={{ flex: 2 }}>字段</span>
            <span style={{ flex: 1.6, marginLeft: 8 }}>操作符</span>
            <span style={{ flex: 1.8, marginLeft: 8 }}>比较值</span>
            <span style={{ width: 32, marginLeft: 8 }} />
          </div>
          {fields.map(({ key, name, ...restField }) => (
            <Space.Compact key={key} style={{ display: 'flex', marginBottom: 8 }} block>
              <Form.Item
                {...restField}
                name={[name, 'field']}
                rules={[{ required: true, message: '请选择字段' }]}
                style={{ flex: 2, marginBottom: 0 }}
              >
                <Select
                  showSearch
                  placeholder={fieldOptions.length ? '选择入参字段' : '先在开始节点定义字段'}
                  options={fieldOptions}
                  notFoundContent="开始节点未定义入参"
                />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'operator']}
                style={{ flex: 1.6, marginBottom: 0, marginLeft: 8 }}
              >
                <Select options={BRANCH_OPERATORS} />
              </Form.Item>
              <Form.Item
                {...restField}
                name={[name, 'value']}
                rules={[{ required: true, message: '请输入比较值' }]}
                style={{ flex: 1.8, marginBottom: 0, marginLeft: 8 }}
              >
                <Input placeholder="比较值" />
              </Form.Item>
              <Button
                type="text"
                danger
                icon={<CloseOutlined />}
                style={{ marginLeft: 8 }}
                onClick={() => remove(name)}
              />
            </Space.Compact>
          ))}
          <Button
            type="dashed"
            onClick={() => add({ field: '', operator: 'eq', value: '' })}
            block
            icon={<PlusOutlined />}
          >
            添加条件（多条件为 AND 关系）
          </Button>
        </>
      )}
    </Form.List>
  )
}

export function NodeConfigDrawer({ open, onClose }: Props) {
  const { message } = App.useApp()
  const selectedNodeId = useAppStore((s) => s.selectedNodeId)
  const nodes = useAppStore((s) => s.nodes)
  const edges = useAppStore((s) => s.edges)
  const updateNodeConfig = useAppStore((s) => s.updateNodeConfig)
  const removeNode = useAppStore((s) => s.removeNode)

  const node = nodes.find((n) => n.id === selectedNodeId)

  // 下游节点列表（参考 dify "下一步" 区域）
  const downstreamNodes = useMemo(() => {
    if (!node) return []
    const targetIds = edges.filter((e) => e.source === node.id).map((e) => e.target)
    return nodes.filter((n) => targetIds.includes(n.id))
  }, [node, nodes, edges])
  const [form] = Form.useForm()
  // 统一在顶层调用 watch，避免条件分支里调用 hook 导致 hook 顺序变化
  const watchedSystemPrompt = (Form.useWatch('system_prompt', form) as string) ?? ''
  const watchedUserPrompt = (Form.useWatch('user_prompt', form) as string) ?? ''
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
      // 把对象转成 key-value 数组供 Form.List 回显（http 的 params 与 headers 都需要）
      for (const key of ['params', 'headers', 'input_mapping']) {
        const v = cfg[key]
        if (v !== undefined && v !== null && typeof v === 'object' && !Array.isArray(v)) {
          cfg[key] = objectToKvArray(v)
        }
      }
      // body 仍是 JSON TextArea，需要字符串化
      if (cfg.body !== undefined && cfg.body !== null && typeof cfg.body !== 'string') {
        cfg.body = JSON.stringify(cfg.body, null, 2)
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
            <OutputVariablesEditor nodeId={node.id} />
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
            <Form.Item label="用户提示词" name="user_prompt" tooltip="对应 OpenAI messages 中的 user 消息，通常用 {{#input.query#}} 引用上游字段">
              <PromptTextArea
                value={watchedUserPrompt}
                onChange={(v) => form.setFieldValue('user_prompt', v)}
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
            <Form.Item label="结构化输出" name="response_format_json" valuePropName="checked" tooltip="开启后模型返回 JSON 对象（需模型支持 response_format）">
              <Switch checkedChildren="JSON" unCheckedChildren="文本" />
            </Form.Item>
            <RetryConfigFields />
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
        // 从 start 节点收集入参字段，作为条件 field 的候选
        const startNode = nodes.find((n) => n.data.nodeType === 'start')
        const startInputs = ((startNode?.data.config?.inputs as Array<{ name: string; type: string }>) ?? [])
          .filter((v) => v && v.name)
        return (
          <>
            <Form.Item label="条件（全部满足走 true 分支）">
              <BranchConditionsEditor startInputs={startInputs} />
            </Form.Item>
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
              label="调用参数"
              name="params"
              tooltip="调用工具时传入的参数，支持 {{#input.字段#}} 占位符"
            >
              <KeyValueEditor
                name="params"
                keyPlaceholder="参数名"
                valuePlaceholder="参数值"
                addText="添加参数"
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
            <Form.Item label="Query 参数" name="params" tooltip="拼接到 URL 后面的 ?key=value 参数，支持 {{#input.query#}}">
              <KeyValueEditor
                name="params"
                keyPlaceholder="参数名"
                valuePlaceholder="参数值"
                addText="添加参数"
              />
            </Form.Item>
            <Form.Item label="请求头" name="headers">
              <KeyValueEditor
                name="headers"
                keyPlaceholder="Header 名，如 Authorization"
                valuePlaceholder="Header 值"
                addText="添加请求头"
              />
            </Form.Item>
            <Form.Item label="请求体" name="body" tooltip="JSON 格式，留空表示无请求体">
              <Input.TextArea rows={4} style={{ fontFamily: 'monospace', fontSize: 12 }} placeholder='{"key": "value"}' />
            </Form.Item>
            <Form.Item label="超时时间" name="timeout_seconds" tooltip="请求超时秒数，超时后节点失败">
              <InputNumber min={1} max={300} style={{ width: '100%' }} addonAfter="秒" />
            </Form.Item>
            <RetryConfigFields />
          </>
        )
      case 'retrieval': {
        const startNodeForRetrieval = nodes.find((n) => n.data.nodeType === 'start')
        const startInputOptions = ((startNodeForRetrieval?.data.config?.inputs as Array<{ name: string }>) ?? [])
          .filter((v) => v && v.name)
          .map((v) => ({ value: v.name, label: v.name }))
        return (
          <>
            <Form.Item label="知识库" name="knowledge_base_id">
              <KnowledgeResourceSelect />
            </Form.Item>
            <Form.Item label="查询字段" name="query_field" tooltip="从开始节点入参中取哪个字段作为检索 query">
              <Select
                allowClear
                showSearch
                placeholder={startInputOptions.length ? '选择开始节点的入参字段' : '先在开始节点定义入参'}
                options={startInputOptions}
                notFoundContent="开始节点未定义入参"
              />
            </Form.Item>
            <Form.Item label="Top K" name="top_k">
              <InputNumber min={1} max={50} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item label="相似度阈值" name="score_threshold" tooltip="低于此分数的召回结果会被过滤（0-1）">
              <Slider min={0} max={1} step={0.05} marks={{ 0: '0', 0.5: '0.5', 1: '1' }} />
            </Form.Item>
          </>
        )
      }
      case 'human_task':
        return (
          <>
            <Form.Item label="指派角色" name="assignee_role">
              <Input placeholder="如 reviewer / approver" />
            </Form.Item>
            <Form.Item label="审批说明" name="instructions">
              <Input.TextArea rows={4} placeholder="告诉审批人需要做什么" />
            </Form.Item>
            <Form.Item label="超时时间" name="timeout_seconds" tooltip="审批人未在限定时间内响应时的等待时长">
              <InputNumber min={60} max={86400} style={{ width: '100%' }} addonAfter="秒" />
            </Form.Item>
            <Form.Item label="超时后动作" name="timeout_action" tooltip="超时后工作流的处理方式">
              <Select
                options={[
                  { value: 'fail', label: '标记为失败（fail）' },
                  { value: 'continue', label: '自动通过并继续（continue）' },
                ]}
              />
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
              label="入参映射"
              name="input_mapping"
              tooltip="父 state 字段 -> 子图 input 字段，如 query -> query"
            >
              <KeyValueEditor
                name="input_mapping"
                keyPlaceholder="父 state 字段"
                valuePlaceholder="子图 input 字段"
                addText="添加映射"
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
        {node && node.data.nodeType !== 'sticky' && (
          <Form.Item label="节点描述" name="description" tooltip="可选，给节点写一句说明，便于团队协作理解">
            <Input.TextArea rows={2} placeholder="例如：调用外部订单系统查询订单状态" />
          </Form.Item>
        )}
        {renderConfigForm()}
      </Form>

      {node && node.data.nodeType !== 'end' && (
        <div style={{ marginTop: 24, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
          <div style={{ fontSize: 13, color: '#595959', marginBottom: 8 }}>下一步</div>
          {downstreamNodes.length === 0 ? (
            <div style={{ fontSize: 12, color: '#999' }}>
              尚未连接下游节点，从本节点右侧圆点拉线到目标节点
            </div>
          ) : (
            <Space direction="vertical" size={6} style={{ width: '100%' }}>
              {downstreamNodes.map((n) => (
                <div
                  key={n.id}
                  style={{
                    padding: '6px 10px',
                    background: '#fafafa',
                    borderRadius: 4,
                    fontSize: 12,
                    color: '#262626',
                  }}
                >
                  <Tag color="blue" style={{ marginInlineEnd: 8 }}>
                    {TYPE_LABEL[n.data.nodeType]}
                  </Tag>
                  {n.id}
                </div>
              ))}
            </Space>
          )}
        </div>
      )}

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
