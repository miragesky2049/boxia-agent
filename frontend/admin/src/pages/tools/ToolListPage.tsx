import { PlusOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Checkbox,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Slider,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'

import {
  importMcpTools,
  parseCurl,
  pullMcpTools,
  testInvokeTool,
  toolsApi,
  type McpPulledTool,
} from '../../api/resources'
import type { Tool, ToolPayload } from '../../api/types'

const TYPE_COLOR: Record<string, string> = {
  http: 'blue',
  mcp: 'purple',
  echo: 'green',
}

interface GatewayConfig {
  timeout_seconds?: number
  retry_max?: number
  circuit_failure_threshold?: number
  circuit_open_seconds?: number
  rate_limit_per_second?: number
}

function ToolEditDrawer({
  tool,
  onClose,
  onSaved,
}: {
  tool: Tool | null
  onClose: () => void
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const [form] = Form.useForm<ToolPayload>()
  const [saving, setSaving] = useState(false)
  const [configText, setConfigText] = useState('{}')
  const [testArgs, setTestArgs] = useState('{}')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<ToolTestInvokeResult | null>(null)

  // MCP 自动同步状态
  const [mcpUrl, setMcpUrl] = useState('')
  const [mcpPulling, setMcpPulling] = useState(false)
  const [mcpPulled, setMcpPulled] = useState<McpPulledTool[]>([])
  const [mcpSelected, setMcpSelected] = useState<Record<string, boolean>>({})
  const [mcpImporting, setMcpImporting] = useState(false)

  // curl 粘贴状态
  const [curlText, setCurlText] = useState('')
  const [parsingCurl, setParsingCurl] = useState(false)

  // gateway 滑块
  const [gateway, setGateway] = useState<GatewayConfig>({})

  useEffect(() => {
    if (tool) {
      form.setFieldsValue({
        name: tool.name,
        description: tool.description,
        type: tool.type,
        is_enabled: tool.is_enabled,
      })
      setConfigText(JSON.stringify(tool.config ?? {}, null, 2))
      const cfg = (tool.config as Record<string, unknown> | null)?.gateway as
        | GatewayConfig
        | undefined
      setGateway(cfg ?? {})
    } else {
      form.resetFields()
      form.setFieldsValue({ type: 'http', is_enabled: true })
      setConfigText('{}')
      setGateway({})
    }
    setTestArgs('{}')
    setTestResult(null)
    setMcpPulled([])
    setMcpSelected({})
    setCurlText('')
  }, [tool, form])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      let config: Record<string, unknown> = {}
      try {
        config = JSON.parse(configText || '{}')
      } catch {
        message.error('工具 config 必须是合法 JSON')
        return
      }
      // 合并 gateway 滑块配置
      if (Object.keys(gateway).length > 0) {
        config.gateway = gateway
      }
      setSaving(true)
      const payload: ToolPayload = { ...values, config }
      if (tool) {
        await toolsApi.update(tool.id, payload)
        message.success('已更新')
      } else {
        await toolsApi.create(payload)
        message.success('已创建')
      }
      onSaved()
      onClose()
    } catch (error) {
      if (error instanceof Error) message.error(error.message)
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    if (!tool) {
      message.warning('请先保存工具后再试调')
      return
    }
    let args: Record<string, unknown>
    try {
      args = JSON.parse(testArgs || '{}')
    } catch {
      message.error('试调参数必须是合法 JSON')
      return
    }
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testInvokeTool(tool.id, args)
      setTestResult(result)
      if (result.success) {
        message.success(`试调成功，耗时 ${result.duration_ms}ms`)
      } else {
        message.error(`试调失败：${result.error}`)
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '试调请求失败')
    } finally {
      setTesting(false)
    }
  }

  const handlePullMcp = async () => {
    if (!mcpUrl.trim()) {
      message.warning('请输入 MCP server URL')
      return
    }
    setMcpPulling(true)
    try {
      const result = await pullMcpTools(mcpUrl.trim())
      setMcpPulled(result.tools)
      const selected: Record<string, boolean> = {}
      result.tools.forEach((t) => {
        selected[t.name] = true
      })
      setMcpSelected(selected)
      message.success(`发现 ${result.tools.length} 个工具`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '拉取 MCP 工具失败')
    } finally {
      setMcpPulling(false)
    }
  }

  const handleImportMcp = async () => {
    const selectedItems = mcpPulled.filter((t) => mcpSelected[t.name])
    if (selectedItems.length === 0) {
      message.warning('请至少勾选一个工具')
      return
    }
    setMcpImporting(true)
    try {
      await importMcpTools(
        mcpUrl.trim(),
        selectedItems.map((t) => ({
          name: t.name,
          description: t.description,
          tool_name_remote: t.name,
          input_schema: t.input_schema,
        })),
      )
      message.success(`已导入 ${selectedItems.length} 个工具`)
      setMcpPulled([])
      setMcpSelected({})
      onSaved()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '批量导入失败')
    } finally {
      setMcpImporting(false)
    }
  }

  const handleParseCurl = async () => {
    if (!curlText.trim()) {
      message.warning('请粘贴 curl 命令')
      return
    }
    setParsingCurl(true)
    try {
      const result = await parseCurl(curlText.trim())
      const current = JSON.parse(configText || '{}') as Record<string, unknown>
      const merged: Record<string, unknown> = {
        ...current,
        url: result.url,
        method: result.method,
        headers: { ...(current.headers as Record<string, string> | undefined), ...result.headers },
      }
      if (result.body) {
        merged.parameters = result.body
      }
      setConfigText(JSON.stringify(merged, null, 2))
      form.setFieldsValue({ type: 'http' })
      if (result.notes.length > 0) {
        message.warning(result.notes.join('；'))
      } else {
        message.success('已回填 HTTP 配置')
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'curl 解析失败')
    } finally {
      setParsingCurl(false)
    }
  }

  const toolType = Form.useWatch('type', form)

  return (
    <Drawer
      title={tool ? `编辑工具：${tool.name}` : '新建工具'}
      open={tool !== null || saving}
      width={680}
      onClose={onClose}
      destroyOnHidden
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={handleSave}>
            保存
          </Button>
        </Space>
      }
    >
      <Tabs
        items={[
          {
            key: 'basic',
            label: '基础信息',
            children: (
              <Form form={form} layout="vertical">
                <Form.Item
                  label="名称"
                  name="name"
                  rules={[{ required: true, message: '请输入工具名称' }]}
                >
                  <Input placeholder="例如：查询天气" />
                </Form.Item>
                <Form.Item label="描述" name="description">
                  <Input.TextArea rows={3} placeholder="给 LLM 看的工具描述" />
                </Form.Item>
                <Form.Item label="类型" name="type" rules={[{ required: true }]}>
                  <Select
                    options={[
                      { value: 'http', label: 'HTTP 工具' },
                      { value: 'mcp', label: 'MCP 工具' },
                      { value: 'echo', label: '内置 Echo' },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="启用" name="is_enabled" valuePropName="checked">
                  <Switch />
                </Form.Item>
              </Form>
            ),
          },
          {
            key: 'config',
            label: '服务连接',
            children: (
              <div>
                {toolType === 'http' && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 13, color: '#595959', marginBottom: 8 }}>
                      粘贴 curl 命令自动回填：
                    </div>
                    <Input.TextArea
                      value={curlText}
                      onChange={(e) => setCurlText(e.target.value)}
                      rows={3}
                      placeholder={'curl https://api.example.com/weather -H "X-Key: xxx" -d \'{"city":"北京"}\''}
                      style={{ fontFamily: 'monospace', fontSize: 12 }}
                    />
                    <Button
                      icon={<ThunderboltOutlined />}
                      loading={parsingCurl}
                      onClick={handleParseCurl}
                      style={{ marginTop: 8 }}
                    >
                      解析 curl
                    </Button>
                  </div>
                )}
                {toolType === 'mcp' && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 13, color: '#595959', marginBottom: 8 }}>
                      输入 MCP server URL 自动同步工具列表：
                    </div>
                    <Space.Compact style={{ width: '100%' }}>
                      <Input
                        value={mcpUrl}
                        onChange={(e) => setMcpUrl(e.target.value)}
                        placeholder="https://mcp.example.com/sse"
                        style={{ fontFamily: 'monospace' }}
                      />
                      <Button type="primary" loading={mcpPulling} onClick={handlePullMcp}>
                        拉取工具
                      </Button>
                    </Space.Compact>
                    {mcpPulled.length > 0 && (
                      <div style={{ marginTop: 12, border: '1px solid #f0f0f0', borderRadius: 4, padding: 12 }}>
                        <div style={{ marginBottom: 8, fontWeight: 500 }}>
                          发现 {mcpPulled.length} 个工具，勾选要导入的：
                        </div>
                        {mcpPulled.map((t) => (
                          <Checkbox
                            key={t.name}
                            checked={mcpSelected[t.name]}
                            onChange={(e) =>
                              setMcpSelected({ ...mcpSelected, [t.name]: e.target.checked })
                            }
                            style={{ display: 'block', marginBottom: 4 }}
                          >
                            <strong>{t.name}</strong>
                            <span style={{ color: '#8c8c8c', marginLeft: 8, fontSize: 12 }}>
                              {t.description || '（无描述）'}
                            </span>
                          </Checkbox>
                        ))}
                        <Button
                          type="primary"
                          loading={mcpImporting}
                          onClick={handleImportMcp}
                          style={{ marginTop: 8 }}
                        >
                          批量导入
                        </Button>
                      </div>
                    )}
                  </div>
                )}
                <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8 }}>
                  HTTP 工具：{'{"url": "...", "method": "GET", "headers": {}, "parameters": {...}}'}
                </div>
                <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8 }}>
                  MCP 工具：{'{"server_url": "...", "tool_name": "...", "input_schema": {...}}'}
                </div>
                <Input.TextArea
                  value={configText}
                  onChange={(e) => setConfigText(e.target.value)}
                  rows={12}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                />
              </div>
            ),
          },
          {
            key: 'gateway',
            label: '高级配置（治理）',
            children: (
              <div>
                <div style={{ fontSize: 13, color: '#595959', marginBottom: 16 }}>
                  跨网调用治理：超时 / 重试 / 熔断 / 限流。留空使用全局默认值。
                </div>
                <Form layout="vertical">
                  <Form.Item label={`超时时间：${gateway.timeout_seconds ?? 45}s`}>
                    <Slider
                      min={5}
                      max={120}
                      step={5}
                      value={gateway.timeout_seconds ?? 45}
                      onChange={(v) => setGateway({ ...gateway, timeout_seconds: v })}
                    />
                  </Form.Item>
                  <Form.Item label={`最大重试次数：${gateway.retry_max ?? 2}`}>
                    <Slider
                      min={0}
                      max={5}
                      value={gateway.retry_max ?? 2}
                      onChange={(v) => setGateway({ ...gateway, retry_max: v })}
                    />
                  </Form.Item>
                  <Form.Item label={`熔断失败阈值：${gateway.circuit_failure_threshold ?? 5} 次`}>
                    <Slider
                      min={2}
                      max={20}
                      value={gateway.circuit_failure_threshold ?? 5}
                      onChange={(v) => setGateway({ ...gateway, circuit_failure_threshold: v })}
                    />
                  </Form.Item>
                  <Form.Item label={`熔断打开时长：${gateway.circuit_open_seconds ?? 30}s`}>
                    <Slider
                      min={10}
                      max={300}
                      step={10}
                      value={gateway.circuit_open_seconds ?? 30}
                      onChange={(v) => setGateway({ ...gateway, circuit_open_seconds: v })}
                    />
                  </Form.Item>
                  <Form.Item label={`限流 QPS：${gateway.rate_limit_per_second ?? 20}/s`}>
                    <Slider
                      min={1}
                      max={100}
                      value={gateway.rate_limit_per_second ?? 20}
                      onChange={(v) => setGateway({ ...gateway, rate_limit_per_second: v })}
                    />
                  </Form.Item>
                </Form>
              </div>
            ),
          },
          {
            key: 'test',
            label: '试运行',
            children: (
              <div>
                <div style={{ marginBottom: 8, fontSize: 13, color: '#595959' }}>
                  入参 JSON（传给 tool.invoke 的 arguments）
                </div>
                <Input.TextArea
                  value={testArgs}
                  onChange={(e) => setTestArgs(e.target.value)}
                  rows={4}
                  style={{ fontFamily: 'monospace', fontSize: 12 }}
                />
                <Button
                  type="primary"
                  style={{ marginTop: 12 }}
                  loading={testing}
                  onClick={handleTest}
                >
                  调用
                </Button>
                {testResult && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ marginBottom: 8 }}>
                      <Tag color={testResult.success ? 'success' : 'error'}>
                        {testResult.success ? '成功' : '失败'}
                      </Tag>
                      <span style={{ marginLeft: 8, color: '#8c8c8c' }}>
                        {testResult.duration_ms}ms
                      </span>
                    </div>
                    {testResult.error && (
                      <pre
                        style={{
                          padding: 12,
                          background: '#fff2f0',
                          borderRadius: 4,
                          color: '#cf1322',
                          fontSize: 12,
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {testResult.error}
                      </pre>
                    )}
                    {testResult.output && (
                      <pre
                        style={{
                          padding: 12,
                          background: '#f6ffed',
                          borderRadius: 4,
                          fontSize: 12,
                          maxHeight: 320,
                          overflow: 'auto',
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {testResult.output}
                      </pre>
                    )}
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />
    </Drawer>
  )
}

interface ToolTestInvokeResult {
  success: boolean
  duration_ms: number
  output: string
  error: string
}

export default function ToolListPage() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<Tool[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [editing, setEditing] = useState<Tool | null>(null)
  const [isCreating, setIsCreating] = useState(false)

  const load = async (p = page, kw = keyword) => {
    setLoading(true)
    try {
      const result = await toolsApi.list({ page: p, page_size: 20, keyword: kw })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载工具列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(1, '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const columns: ColumnsType<Tool> = useMemo(
    () => [
      { title: '名称', dataIndex: 'name' },
      {
        title: '类型',
        dataIndex: 'type',
        width: 100,
        render: (t: string) => <Tag color={TYPE_COLOR[t] ?? 'default'}>{t}</Tag>,
      },
      { title: '描述', dataIndex: 'description', ellipsis: true },
      {
        title: '作用域',
        dataIndex: 'is_platform',
        width: 100,
        render: (p: boolean) => (p ? <Tag color="geekblue">平台</Tag> : <Tag color="green">租户</Tag>),
      },
      {
        title: '启用',
        dataIndex: 'is_enabled',
        width: 80,
        render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '是' : '否'}</Tag>,
      },
      {
        title: '操作',
        width: 160,
        render: (_, record) => (
          <Space>
            <Button type="link" size="small" onClick={() => setEditing(record)}>
              编辑
            </Button>
            <Button
              type="link"
              size="small"
              danger
              onClick={() => {
                Modal.confirm({
                  title: '确认删除该工具？',
                  onOk: async () => {
                    try {
                      await toolsApi.remove(record.id)
                      message.success('已删除')
                      load()
                    } catch (error) {
                      message.error(error instanceof Error ? error.message : '删除失败')
                    }
                  },
                })
              }}
            >
              删除
            </Button>
          </Space>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  return (
    <div className="page-card">
      <Space style={{ marginBottom: 16 }}>
        <Input.Search
          placeholder="按名称搜索"
          allowClear
          onSearch={(kw) => {
            setKeyword(kw)
            setPage(1)
            load(1, kw)
          }}
          style={{ width: 240 }}
        />
        <Button icon={<ReloadOutlined />} onClick={() => load()}>
          刷新
        </Button>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditing(null)
            setIsCreating(true)
          }}
        >
          新建工具
        </Button>
      </Space>

      <Table<Tool>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: (p) => {
            setPage(p)
            load(p)
          },
        }}
      />

      <ToolEditDrawer
        tool={editing}
        onClose={() => {
          setEditing(null)
          setIsCreating(false)
        }}
        onSaved={() => load()}
        key={editing?.id ?? (isCreating ? 'new' : 'none')}
      />
    </div>
  )
}
