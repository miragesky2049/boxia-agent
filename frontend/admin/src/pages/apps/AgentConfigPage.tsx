// 0074 智能体配置页：表单是画布 agent_loop 节点的视图（画布为唯一事实源）。
// 覆盖 人设/模型/推理模式/开场白/推荐问题/工具/知识库/短期记忆（M1）
// + MCP 快照/工作流即工具/Token 预算（0074 PRD F6/F7/F11，M2）。
import { App, Button, Card, Checkbox, Form, Input, InputNumber, Radio, Select, Space, Switch } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getAgentConfig,
  saveAgentConfig,
  type AgentConfigForm,
  type AgentDatasetEntry,
} from '../../api/agentConfig'
import {
  getApp,
  listApps,
  listAvailableModels,
  type Application,
  type ModelItem,
} from '../../api/apps'
import { listDatasets, type DatasetItem } from '../../api/datasets'
import { discoverMcpTools, type McpToolSnapshot } from '../../api/mcpConfig'

// 后端 agent_config 校验的条目上限，与 domain/canvas/agent_config.py 常量对齐
const MAX_MCP_SERVERS = 5
const MAX_MCP_TOOLS_PER_SERVER = 20
const MAX_WORKFLOWS = 5

// tools 在表单里的编辑形态：parameters 用 JSON 文本承载
interface ToolRow {
  name?: string
  description?: string
  parametersText?: string
  // antd Form 泛型对 unknown 值推导过严，此处仅做透传不参与渲染
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rest?: Record<string, any>
}

// 知识库行的表单编辑形态（AgentDatasetEntry 含索引签名，antd 泛型推导过严，此处收窄）
interface DatasetRow {
  datasetId?: string
  name?: string
  description?: string
  mode?: 'onDemand' | 'always'
  topK?: number
}

// MCP server 行的编辑形态：headers 用 JSON 文本承载，enabledTools 为勾选快照
interface McpServerRow {
  serverUrl?: string
  name?: string
  headersText?: string
  enabledTools?: McpToolSnapshot[]
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  rest?: Record<string, any>
}

// 工作流即工具条目（workflow_N 名称按本列表配置序合成，不存快照名）
interface WorkflowRow {
  applicationId?: string
  name?: string
  description?: string
}

interface AgentConfigValues {
  systemPrompt: string
  modleName: string
  maxToolRounds: number
  reasoningMode: 'react' | 'planExecuteReflect'
  openingRemarks: string
  suggestedQuestions?: string[]
  tools?: ToolRow[]
  datasets?: DatasetRow[]
  mcpServers?: McpServerRow[]
  workflows?: WorkflowRow[]
  tokenBudget?: number | null
  memory: { shortTerm: { enabled: boolean; windowTurns: number; tokenBudget: number } }
  /** 0074 PRD F10：待人工审批的敏感工具名清单 */
  sensitiveToolNames?: string[]
  /** 0074 PRD F9：视觉开关 */
  visionEnabled?: boolean
}

function toFormValues(config: AgentConfigForm): AgentConfigValues {
  return {
    systemPrompt: config.systemPrompt,
    modleName: config.modleName,
    maxToolRounds: config.maxToolRounds,
    reasoningMode: config.reasoningMode,
    openingRemarks: config.openingRemarks,
    suggestedQuestions: config.suggestedQuestions,
    tools: (config.tools || []).map((tool) => ({
      name: String(tool.name ?? ''),
      description: String(tool.description ?? ''),
      parametersText: JSON.stringify(tool.parameters ?? { type: 'object', properties: {} }, null, 2),
      rest: Object.fromEntries(
        Object.entries(tool).filter(([key]) => !['name', 'description', 'parameters'].includes(key)),
      ),
    })),
    datasets: config.datasets,
    mcpServers: config.mcpServers.map((entry) => ({
      serverUrl: String(entry.serverUrl ?? ''),
      name: String(entry.name ?? ''),
      headersText: entry.headers ? JSON.stringify(entry.headers, null, 2) : '',
      enabledTools: Array.isArray(entry.enabledTools)
        ? (entry.enabledTools as McpToolSnapshot[])
        : [],
      rest: Object.fromEntries(
        Object.entries(entry).filter(
          ([key]) => !['serverUrl', 'name', 'headers', 'enabledTools'].includes(key),
        ),
      ),
    })),
    workflows: config.workflows.map((entry) => ({
      applicationId: String(entry.applicationId ?? ''),
      name: String(entry.name ?? ''),
      description: String(entry.description ?? ''),
    })),
    tokenBudget: config.tokenBudget ?? undefined,
    memory: { shortTerm: config.memory.shortTerm },
    sensitiveToolNames: (config.sensitiveTools || [])
      .map((entry) => String((entry as { name?: unknown }).name ?? ''))
      .filter(Boolean),
    visionEnabled: Boolean(config.visionEnabled),
  }
}

// 0074 PRD F10：当前配置暴露给模型的全部工具名（敏感工具勾选区数据源）。
// 知识库检索/工作流为合成前缀名，MCP 取勾选快照名，与运行时白名单口径一致。
function collectCandidateToolNames(
  tools: ToolRow[] | undefined,
  datasets: DatasetRow[] | undefined,
  workflows: WorkflowRow[] | undefined,
  mcpServers: McpServerRow[] | undefined,
): string[] {
  const names = new Set<string>()
  for (const row of tools || []) {
    const name = (row.name || '').trim()
    if (name) names.add(name)
  }
  ;(datasets || []).forEach((entry, index) => {
    if (entry?.datasetId) names.add(`knowledge_search_${index + 1}`)
  })
  ;(workflows || []).forEach((entry, index) => {
    if ((entry.applicationId || '').trim()) names.add(`workflow_${index + 1}`)
  })
  for (const server of mcpServers || []) {
    for (const tool of server.enabledTools || []) names.add(tool.name)
  }
  return [...names]
}

// 单个 MCP server 的编辑卡：discover 拉清单 → 勾选存快照（0074 PRD F6.1/F6.3）
function McpServerCard({
  fieldName,
  onRemove,
}: {
  fieldName: number
  onRemove: () => void
}) {
  const { message } = App.useApp()
  const form = Form.useFormInstance()
  const [discovered, setDiscovered] = useState<McpToolSnapshot[]>([])
  const [discovering, setDiscovering] = useState(false)
  const enabledTools: McpToolSnapshot[] =
    Form.useWatch(['mcpServers', fieldName, 'enabledTools'], form) ?? []

  // 打开页面时把已有快照作为勾选清单初始来源，避免重进页面只见勾选项不见清单
  useEffect(() => {
    const current = form.getFieldValue(['mcpServers', fieldName, 'enabledTools'])
    if (Array.isArray(current) && current.length > 0) {
      setDiscovered(current as McpToolSnapshot[])
    }
  }, [form, fieldName])

  const handleDiscover = useCallback(async () => {
    const serverUrl = String(form.getFieldValue(['mcpServers', fieldName, 'serverUrl']) || '').trim()
    if (!serverUrl) {
      message.warning('请先填写 MCP 服务地址')
      return
    }
    let headers: Record<string, string> | undefined
    const text = String(form.getFieldValue(['mcpServers', fieldName, 'headersText']) || '').trim()
    if (text) {
      try {
        const parsed = JSON.parse(text)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('bad')
        headers = parsed as Record<string, string>
      } catch {
        message.error('请求头需为合法 JSON 对象，如 {"Authorization": "Bearer xxx"}')
        return
      }
    }
    setDiscovering(true)
    try {
      const result = await discoverMcpTools(serverUrl, headers)
      setDiscovered(result.tools)
      if (result.fromCache) message.info('使用了服务端 30 秒缓存结果')
      else message.success(`发现 ${result.tools.length} 个工具`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'MCP 工具发现失败')
    } finally {
      setDiscovering(false)
    }
  }, [fieldName, form, message])

  const toggleTool = (tool: McpToolSnapshot, checked: boolean) => {
    const current = enabledTools ?? []
    const kept = current.filter((item) => item.name !== tool.name)
    const next = checked ? [...kept, tool] : kept
    if (next.length > MAX_MCP_TOOLS_PER_SERVER) {
      message.warning(`单个 MCP 服务最多启用 ${MAX_MCP_TOOLS_PER_SERVER} 个工具`)
      return
    }
    form.setFieldValue(['mcpServers', fieldName, 'enabledTools'], next)
  }

  return (
    <Card
      size="small"
      style={{ marginBottom: 8 }}
      title={
        <span style={{ fontSize: 13 }}>
          {enabledTools.length > 0 ? `已启用 ${enabledTools.length} 个工具` : '未勾选工具'}
        </span>
      }
      extra={
        <Button type="text" danger size="small" onClick={onRemove}>
          删除
        </Button>
      }
    >
      <Space align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
        <Form.Item
          name={[fieldName, 'serverUrl']}
          noStyle
          rules={[{ required: true, message: 'MCP 服务地址必填' }]}
        >
          <Input style={{ width: 320 }} placeholder="https://example.com/mcp" />
        </Form.Item>
        <Form.Item name={[fieldName, 'name']} noStyle>
          <Input style={{ width: 140 }} placeholder="显示名（可选）" />
        </Form.Item>
        <Button size="small" loading={discovering} onClick={() => void handleDiscover()}>
          发现工具
        </Button>
      </Space>
      <Form.Item
        name={[fieldName, 'headersText']}
        label="请求头（JSON，可选）"
        style={{ marginBottom: 8 }}
      >
        <Input.TextArea rows={2} style={{ fontFamily: 'monospace', fontSize: 12 }} />
      </Form.Item>
      {discovered.length > 0 ? (
        <div style={{ maxHeight: 180, overflow: 'auto' }}>
          {discovered.map((tool) => (
            <div key={tool.name} style={{ marginBottom: 4 }}>
              <Checkbox
                checked={enabledTools.some((item) => item.name === tool.name)}
                onChange={(e) => toggleTool(tool, e.target.checked)}
              >
                <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{tool.name}</span>
                {tool.description ? (
                  <span style={{ color: '#9ca3af', fontSize: 12 }}> — {tool.description}</span>
                ) : null}
              </Checkbox>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: '#9ca3af', fontSize: 12 }}>
          点击「发现工具」拉取该 MCP 服务的工具清单后勾选；勾选结果将快照进配置，运行时不再连接发现接口。
        </div>
      )}
    </Card>
  )
}

export default function AgentConfigPage() {
  const { id = '' } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [form] = Form.useForm<AgentConfigValues>()
  const [appInfo, setAppInfo] = useState<Application | null>(null)
  const [models, setModels] = useState<ModelItem[]>([])
  const [datasets, setDatasets] = useState<DatasetItem[]>([])
  // 0074 PRD F7：可挂载为工具的工作流应用列表（工作流即工具选择器数据源）
  const [workflowApps, setWorkflowApps] = useState<Application[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  // 服务端读回的完整配置：保存时透传本期不编辑的扩展键
  const baseConfigRef = useRef<AgentConfigForm | null>(null)

  // 0074 PRD F9/F10：敏感工具勾选区与视觉门控依赖的实时表单值
  const watchedTools = Form.useWatch('tools', form)
  const watchedDatasets = Form.useWatch('datasets', form)
  const watchedWorkflows = Form.useWatch('workflows', form)
  const watchedMcp = Form.useWatch('mcpServers', form)
  const watchedModel = Form.useWatch('modleName', form)
  const candidateToolNames = useMemo(
    () => collectCandidateToolNames(watchedTools, watchedDatasets, watchedWorkflows, watchedMcp),
    [watchedTools, watchedDatasets, watchedWorkflows, watchedMcp],
  )
  // 能力标记为后端 snake_case supports_vision（models 目录 capabilities 透传）
  const visionSupported = Boolean(
    models.find((m) => m.model_id === watchedModel)?.capabilities?.supports_vision,
  )

  useEffect(() => {
    let alive = true
    void (async () => {
      try {
        const [app, config, modelItems, datasetItems, allApps] = await Promise.all([
          getApp(id),
          getAgentConfig(id),
          listAvailableModels(),
          listDatasets(),
          listApps(),
        ])
        if (!alive) return
        if (app.flow_type !== 'agent') {
          message.error('该应用不是智能体类型')
          navigate('/apps', { replace: true })
          return
        }
        baseConfigRef.current = config
        setAppInfo(app)
        setModels(modelItems)
        setDatasets(datasetItems)
        setWorkflowApps(allApps.filter((a) => a.flow_type === 'workflow' && a.id !== id))
        form.setFieldsValue(toFormValues(config))
      } catch (error) {
        if (alive) message.error(error instanceof Error ? error.message : '加载智能体配置失败')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => {
      alive = false
    }
  }, [id, form, message, navigate])

  const handleSave = useCallback(async () => {
    const base = baseConfigRef.current
    if (!base) return
    let values: AgentConfigValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const tools: Array<Record<string, unknown>> = []
    for (const row of values.tools || []) {
      const name = (row.name || '').trim()
      if (!name) {
        message.error('工具名不能为空')
        return
      }
      let parameters: unknown
      try {
        parameters = JSON.parse(row.parametersText || '{}')
      } catch {
        message.error(`工具「${name}」的参数不是合法 JSON`)
        return
      }
      tools.push({ ...(row.rest || {}), name, description: row.description || '', parameters })
    }
    // MCP 快照条目：headers 收 JSON 文本，enabledTools 为勾选快照（0074 PRD F6）
    const mcpServers: Array<Record<string, unknown>> = []
    for (const row of values.mcpServers || []) {
      const serverUrl = (row.serverUrl || '').trim()
      if (!serverUrl) {
        message.error('MCP 服务地址不能为空')
        return
      }
      let headers: Record<string, string> | undefined
      const headersText = (row.headersText || '').trim()
      if (headersText) {
        try {
          const parsed = JSON.parse(headersText)
          if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('bad')
          headers = parsed as Record<string, string>
        } catch {
          message.error(`MCP 服务「${serverUrl}」的请求头不是合法 JSON 对象`)
          return
        }
      }
      mcpServers.push({
        ...(row.rest || {}),
        serverUrl,
        name: (row.name || '').trim(),
        ...(headers ? { headers } : {}),
        enabledTools: row.enabledTools ?? [],
      })
    }
    const workflows = (values.workflows || [])
      .filter((entry) => (entry.applicationId || '').trim())
      .map((entry) => ({
        applicationId: (entry.applicationId || '').trim(),
        name: entry.name || '',
        description: entry.description || '',
      }))
    const payload: AgentConfigForm = {
      ...base,
      systemPrompt: values.systemPrompt,
      modleName: values.modleName,
      maxToolRounds: values.maxToolRounds ?? base.maxToolRounds,
      reasoningMode: values.reasoningMode,
      openingRemarks: values.openingRemarks || '',
      suggestedQuestions: (values.suggestedQuestions || []).filter((q) => (q || '').trim()),
      tools,
      datasets: (values.datasets || []).filter((entry) => entry?.datasetId) as AgentDatasetEntry[],
      mcpServers,
      workflows,
      tokenBudget: values.tokenBudget ?? null,
      memory: { shortTerm: { ...base.memory.shortTerm, ...values.memory.shortTerm } },
      // 0074 PRD F10：仅持久化被勾选的敏感工具名（后端节点按 name 集合门控）
      sensitiveTools: (values.sensitiveToolNames || []).map((name) => ({ name })),
      // 0074 PRD F9：视觉开关（模型不支持时强制关闭，防存量配置漂移）
      visionEnabled: visionSupported ? Boolean(values.visionEnabled) : false,
    }
    setSaving(true)
    try {
      const saved = await saveAgentConfig(id, payload)
      baseConfigRef.current = saved
      form.setFieldsValue(toFormValues(saved))
      message.success('智能体配置已保存（生成新的画布版本）')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }, [form, id, message, visionSupported])

  return (
    <div style={{ padding: 24, maxWidth: 880, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <Space>
          <Button onClick={() => navigate('/apps')}>返回列表</Button>
          <span style={{ fontSize: 16, fontWeight: 600 }}>{appInfo?.name || '智能体配置'}</span>
        </Space>
        <Space>
          <Button onClick={() => navigate(`/apps/${id}/edit`)}>打开画布</Button>
          <Button type="primary" loading={saving} disabled={loading} onClick={handleSave}>
            保存
          </Button>
        </Space>
      </Space>

      <Form form={form} layout="vertical" disabled={loading}>
        <Card title="人设与回复逻辑" style={{ marginBottom: 16 }}>
          <Form.Item
            name="systemPrompt"
            label="人设"
            rules={[{ required: true, message: '请填写人设（系统提示词）' }]}
          >
            <Input.TextArea rows={6} maxLength={4000} showCount placeholder="描述角色、能力与边界" />
          </Form.Item>
          <Form.Item
            name="modleName"
            label="模型"
            rules={[{ required: true, message: '请选择模型' }]}
          >
            <Select
              placeholder="选择模型"
              options={models.map((m) => ({
                value: m.model_id,
                label: `${m.display_name}（${m.provider_name}）`,
              }))}
            />
          </Form.Item>
          <Space size={48} wrap>
            <Form.Item name="maxToolRounds" label="最大工具调用轮次" tooltip="防单轮成本失控，1~50">
              <InputNumber min={1} max={50} />
            </Form.Item>
            <Form.Item
              name="reasoningMode"
              label="推理模式"
              tooltip="规划-执行-反思会多付计划/评审的模型调用成本；复杂任务（多子目标、需自查纠偏）建议开启"
            >
              <Radio.Group>
                <Radio value="react">快速反应（ReAct）</Radio>
                <Radio value="planExecuteReflect">规划-执行-反思</Radio>
              </Radio.Group>
            </Form.Item>
            {/* 0074 PRD F11：单 run token 预算，超限后拒绝执行后续工具调用 */}
            <Form.Item
              name="tokenBudget"
              label="单轮 Token 预算"
              tooltip="累计（输入+输出）达到预算后不再执行新工具、要求模型收敛作答；留空为不限制"
            >
              <InputNumber min={1000} max={2000000} step={1000} style={{ width: 140 }} placeholder="不限制" />
            </Form.Item>
            {/* 0074 PRD F9（M3）：视觉开关，仅所选模型能力支持时可开 */}
            <Form.Item
              name="visionEnabled"
              label="图片输入"
              tooltip={
                visionSupported
                  ? '开启后用户端可附带图片，按多模态格式传给模型'
                  : '当前所选模型不支持视觉输入，保存时将强制关闭'
              }
            >
              <Switch disabled={!visionSupported} checkedChildren="开" unCheckedChildren="关" />
            </Form.Item>
          </Space>
        </Card>

        <Card title="开场白" style={{ marginBottom: 16 }}>
          <Form.Item name="openingRemarks" label="开场白（用户进入对话时自动发送）">
            <Input.TextArea rows={3} maxLength={2000} showCount />
          </Form.Item>
          <Form.List name="suggestedQuestions">
            {(fields, { add, remove }) => (
              <div>
                <div style={{ marginBottom: 8, color: '#6b7280', fontSize: 13 }}>
                  开场问题（最多 4 条）
                </div>
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item name={[field.name]} noStyle>
                      <Input style={{ width: 420 }} maxLength={200} />
                    </Form.Item>
                    <Button type="text" danger onClick={() => remove(field.name)}>
                      删除
                    </Button>
                  </Space>
                ))}
                {fields.length < 4 && (
                  <Button type="dashed" onClick={() => add('')}>
                    + 添加问题
                  </Button>
                )}
              </div>
            )}
          </Form.List>
        </Card>

        <Card title="知识库" style={{ marginBottom: 16 }}>
          <Form.List name="datasets">
            {(fields, { add, remove }) => (
              <div>
                {fields.length === 0 && (
                  <div style={{ color: '#9ca3af', fontSize: 13, marginBottom: 8 }}>
                    未关联知识库。按需检索模式下模型自主调用检索工具；自动注入模式每轮执行前检索并附参考资料。
                  </div>
                )}
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                    <Form.Item name={[field.name, 'datasetId']} noStyle rules={[{ required: true, message: '选择知识库' }]}>
                      <Select
                        style={{ width: 220 }}
                        placeholder="选择知识库"
                        showSearch
                        optionFilterProp="label"
                        options={datasets.map((d) => ({ value: d.id, label: d.title }))}
                        onChange={(value: string) => {
                          const hit = datasets.find((d) => d.id === value)
                          if (hit) form.setFieldValue(['datasets', field.name, 'name'], hit.title)
                        }}
                      />
                    </Form.Item>
                    <Form.Item name={[field.name, 'mode']} noStyle initialValue="onDemand">
                      <Select
                        style={{ width: 130 }}
                        options={[
                          { value: 'onDemand', label: '按需检索' },
                          { value: 'always', label: '自动注入' },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item name={[field.name, 'topK']} noStyle initialValue={5}>
                      <InputNumber min={1} max={20} style={{ width: 90 }} addonAfter="条" />
                    </Form.Item>
                    <Button type="text" danger onClick={() => remove(field.name)}>
                      删除
                    </Button>
                  </Space>
                ))}
                {fields.length < 5 && (
                  <Button type="dashed" onClick={() => add({ mode: 'onDemand', topK: 5 })}>
                    + 添加知识库
                  </Button>
                )}
              </div>
            )}
          </Form.List>
        </Card>

        <Card title="记忆" style={{ marginBottom: 16 }}>
          <Space size={48} wrap>
            <Form.Item
              name={['memory', 'shortTerm', 'enabled']}
              label="短期记忆"
              valuePropName="checked"
              tooltip="开启后服务端自动携带近若干轮对话（user 端无需前端传 history）"
            >
              <Switch />
            </Form.Item>
            <Form.Item name={['memory', 'shortTerm', 'windowTurns']} label="窗口轮数">
              <InputNumber min={1} max={100} />
            </Form.Item>
            <Form.Item name={['memory', 'shortTerm', 'tokenBudget']} label="历史 Token 预算">
              <InputNumber min={500} max={200000} step={500} style={{ width: 140 }} />
            </Form.Item>
          </Space>
        </Card>

        <Card title="工具" style={{ marginBottom: 16 }}>
          <Form.List name="tools">
            {(fields, { add, remove }) => (
              <div>
                {fields.length === 0 && (
                  <div style={{ color: '#9ca3af', fontSize: 13, marginBottom: 8 }}>
                    未声明工具。智能体只能回答问题、调用知识库检索工具。
                  </div>
                )}
                {fields.map((field) => (
                  <Card
                    key={field.key}
                    size="small"
                    style={{ marginBottom: 8 }}
                    extra={
                      <Button type="text" danger size="small" onClick={() => remove(field.name)}>
                        删除
                      </Button>
                    }
                  >
                    <Space align="start" style={{ display: 'flex' }}>
                      <Form.Item name={[field.name, 'name']} noStyle rules={[{ required: true, message: '工具名必填' }]}>
                        <Input style={{ width: 200 }} placeholder="工具名（与租户工具目录一致）" />
                      </Form.Item>
                      <Form.Item name={[field.name, 'description']} noStyle>
                        <Input style={{ width: 320 }} placeholder="给模型看的功能说明" />
                      </Form.Item>
                    </Space>
                    <Form.Item
                      name={[field.name, 'parametersText']}
                      label="参数 Schema（JSON）"
                      style={{ marginTop: 8, marginBottom: 0 }}
                    >
                      <Input.TextArea rows={4} style={{ fontFamily: 'monospace', fontSize: 12 }} />
                    </Form.Item>
                  </Card>
                ))}
                <Button
                  type="dashed"
                  block
                  onClick={() =>
                    add({
                      name: '',
                      description: '',
                      parametersText: JSON.stringify({ type: 'object', properties: {} }, null, 2),
                    })
                  }
                >
                  + 添加工具
                </Button>
              </div>
            )}
          </Form.List>
          <div style={{ marginTop: 8, color: '#9ca3af', fontSize: 12 }}>
            工具名不得以 knowledge_search_ 或 workflow_ 开头（知识库检索与工作流工具保留前缀）。
          </div>

          {/* 0074 PRD F10（M3）：敏感工具勾选后该次调用挂起待人工审批；候选=当前配置全集口径 */}
          <div style={{ marginTop: 12 }}>
            <div style={{ marginBottom: 4, fontSize: 13 }}>敏感工具（需人工审批后执行）</div>
            {candidateToolNames.length === 0 ? (
              <div style={{ color: '#9ca3af', fontSize: 12 }}>
                暂无可勾选的工具，请先在上方声明工具或挂载知识库/工作流/MCP。
              </div>
            ) : (
              <Form.Item name="sensitiveToolNames" noStyle>
                <Checkbox.Group options={candidateToolNames} />
              </Form.Item>
            )}
          </div>
        </Card>

        {/* 0074 PRD F7：工作流即工具。workflow_N 合成名按本列表配置序，挂载时自动带出 start 参数 schema */}
        <Card title="工作流工具" style={{ marginBottom: 16 }}>
          <Form.List name="workflows">
            {(fields, { add, remove }) => (
              <div>
                {fields.length === 0 && (
                  <div style={{ color: '#9ca3af', fontSize: 13, marginBottom: 8 }}>
                    未挂载工作流。挂载后模型可按 workflow_1、workflow_2… 调用所选工作流，入参即工作流启动参数。
                  </div>
                )}
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ display: 'flex', marginBottom: 8 }}>
                    <span style={{ color: '#9ca3af', fontSize: 12 }}>workflow_{field.name + 1}</span>
                    <Form.Item
                      name={[field.name, 'applicationId']}
                      noStyle
                      rules={[{ required: true, message: '选择工作流' }]}
                    >
                      <Select
                        style={{ width: 260 }}
                        placeholder="选择工作流应用"
                        showSearch
                        optionFilterProp="label"
                        options={workflowApps.map((w) => ({ value: w.id, label: w.name }))}
                        onChange={(value: string) => {
                          const hit = workflowApps.find((w) => w.id === value)
                          form.setFieldValue(['workflows', field.name, 'name'], hit?.name ?? '')
                          form.setFieldValue(['workflows', field.name, 'description'], hit?.description ?? '')
                        }}
                      />
                    </Form.Item>
                    <Form.Item name={[field.name, 'description']} noStyle>
                      <Input style={{ width: 240 }} placeholder="给模型看的说明（默认取应用描述）" />
                    </Form.Item>
                    <Button type="text" danger onClick={() => remove(field.name)}>
                      删除
                    </Button>
                  </Space>
                ))}
                {fields.length < MAX_WORKFLOWS && (
                  <Button type="dashed" onClick={() => add({ applicationId: '', name: '', description: '' })}>
                    + 挂载工作流
                  </Button>
                )}
                <div style={{ marginTop: 8, color: '#9ca3af', fontSize: 12 }}>
                  运行禁止循环挂载（含跨应用成环）与超过 3 层嵌套；被挂工作流需对当前用户可见。
                </div>
              </div>
            )}
          </Form.List>
        </Card>

        {/* 0074 PRD F6：MCP 服务。discover 勾选后快照进配置，运行时按快照直连 call_tool */}
        <Card title="MCP 服务" style={{ marginBottom: 16 }}>
          <Form.List name="mcpServers">
            {(fields, { add, remove }) => (
              <div>
                {fields.length === 0 && (
                  <div style={{ color: '#9ca3af', fontSize: 13, marginBottom: 8 }}>
                    未连接 MCP 服务。添加后点击「发现工具」拉取清单，勾选需要暴露给模型的工具。
                  </div>
                )}
                {fields.map((field) => (
                  <McpServerCard
                    key={field.key}
                    fieldName={field.name}
                    onRemove={() => remove(field.name)}
                  />
                ))}
                {fields.length < MAX_MCP_SERVERS && (
                  <Button
                    type="dashed"
                    onClick={() => add({ serverUrl: '', name: '', headersText: '', enabledTools: [] })}
                  >
                    + 添加 MCP 服务
                  </Button>
                )}
              </div>
            )}
          </Form.List>
        </Card>
      </Form>
    </div>
  )
}
