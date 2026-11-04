import {
  CheckCircleOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  getApplicationInputs,
  listMyApps,
  runApplication,
  type ApplicationInput,
  type MyApp,
  type RunResult,
} from '../../api/apps'

function JsonBlock({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') {
    return <Typography.Text type="secondary">—</Typography.Text>
  }
  let text: string
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  } catch {
    text = String(value)
  }
  return (
    <pre
      style={{
        margin: 0,
        padding: 8,
        background: '#f5f5f5',
        borderRadius: 4,
        fontSize: 12,
        maxHeight: 360,
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}
    >
      {text}
    </pre>
  )
}

function defaultValueFor(input: ApplicationInput): unknown {
  if (input.default !== undefined && input.default !== null && input.default !== '') {
    return input.default
  }
  switch (input.type) {
    case 'number':
      return 0
    case 'boolean':
      return false
    case 'json':
      return ''
    default:
      return ''
  }
}

function renderField(
  input: ApplicationInput,
  value: unknown,
  onChange: (v: unknown) => void,
) {
  switch (input.type) {
    case 'number':
      return (
        <InputNumber
          style={{ width: '100%' }}
          value={typeof value === 'number' ? value : Number(value) || 0}
          onChange={(v) => onChange(v ?? 0)}
        />
      )
    case 'boolean':
      return (
        <Switch checked={Boolean(value)} onChange={(v) => onChange(v)} />
      )
    case 'json':
      return (
        <Input.TextArea
          rows={6}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
          value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
          placeholder='例如：{"key": "value"}'
          onChange={(e) => onChange(e.target.value)}
        />
      )
    default:
      return (
        <Input
          value={typeof value === 'string' ? value : String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
        />
      )
  }
}

export default function RunPage() {
  const { appId } = useParams<{ appId: string }>()
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [app, setApp] = useState<MyApp | null>(null)
  const [loadingApp, setLoadingApp] = useState(true)
  const [inputDefs, setInputDefs] = useState<ApplicationInput[]>([])
  const [loadingDefs, setLoadingDefs] = useState(false)
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [inputsText, setInputsText] = useState('{\n\n}')
  const [advancedMode, setAdvancedMode] = useState(false)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)

  useEffect(() => {
    if (!appId) return
    setLoadingApp(true)
    listMyApps()
      .then((items) => {
        const found = items.find((i) => i.application_id === appId) ?? null
        setApp(found)
        if (!found) {
          message.warning('未找到该应用的开通记录，请先从应用市场开通')
        }
      })
      .catch((error) => {
        message.error(error instanceof Error ? error.message : '加载应用信息失败')
      })
      .finally(() => setLoadingApp(false))
  }, [appId, message])

  useEffect(() => {
    if (!appId) return
    setLoadingDefs(true)
    getApplicationInputs(appId)
      .then((defs) => {
        setInputDefs(defs)
        const init: Record<string, unknown> = {}
        defs.forEach((d) => {
          init[d.name] = defaultValueFor(d)
        })
        setFormValues(init)
        if (defs.length === 0) {
          setAdvancedMode(true)
        }
      })
      .catch(() => {
        setAdvancedMode(true)
      })
      .finally(() => setLoadingDefs(false))
  }, [appId])

  const serializedInputs = useMemo<Record<string, unknown>>(() => {
    if (advancedMode) {
      const trimmed = inputsText.trim()
      if (!trimmed) return {}
      try {
        const parsed = JSON.parse(trimmed)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return parsed as Record<string, unknown>
        }
      } catch {
        return null as unknown as Record<string, unknown>
      }
      return null as unknown as Record<string, unknown>
    }
    const out: Record<string, unknown> = {}
    for (const def of inputDefs) {
      const raw = formValues[def.name]
      if (def.type === 'json') {
        if (typeof raw === 'string' && raw.trim()) {
          try {
            out[def.name] = JSON.parse(raw)
          } catch {
            return null as unknown as Record<string, unknown>
          }
        } else {
          out[def.name] = raw ?? null
        }
      } else {
        out[def.name] = raw
      }
    }
    return out
  }, [advancedMode, inputsText, inputDefs, formValues])

  const handleRun = async () => {
    if (!appId) return
    if (serializedInputs === null) {
      message.error(advancedMode ? 'inputs JSON 解析失败' : '存在 JSON 字段无法解析')
      return
    }
    setRunning(true)
    setResult(null)
    try {
      const res = await runApplication(appId, serializedInputs)
      setResult(res)
      if (res.status === 'success') {
        message.success('运行完成')
      } else if (res.status === 'waiting_approval') {
        message.info('运行已暂停，等待人审审批')
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '运行失败')
    } finally {
      setRunning(false)
    }
  }

  if (loadingApp || loadingDefs) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <LoadingOutlined />
      </div>
    )
  }

  if (!app) {
    return (
      <div className="page-card">
        <Empty description="未找到已开通的应用" />
      </div>
    )
  }

  return (
    <div className="page-card">
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Space>
          <PlayCircleOutlined style={{ fontSize: 22, color: '#1677ff' }} />
          <Typography.Title level={4} style={{ margin: 0 }}>
            运行「{app.name}」
          </Typography.Title>
        </Space>
        <Space>
          {inputDefs.length > 0 && (
            <Button type="link" onClick={() => setAdvancedMode((v) => !v)}>
              {advancedMode ? '切换到表单模式' : '高级模式（JSON）'}
            </Button>
          )}
          <Button onClick={() => navigate(`/marketplace/apps/${appId}/runs`)}>
            查看运行历史
          </Button>
        </Space>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        {app.description || '暂无描述'}
      </Typography.Paragraph>

      <Card size="small" title="输入参数" style={{ marginTop: 16 }}>
        {advancedMode ? (
          <Input.TextArea
            value={inputsText}
            onChange={(e) => setInputsText(e.target.value)}
            rows={8}
            style={{ fontFamily: 'monospace', fontSize: 13 }}
            placeholder='例如：{"query": "查一下快递 SF123456"}'
          />
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            {inputDefs.map((def) => (
              <div key={def.name}>
                <Typography.Text strong>
                  {def.name}
                  {def.required && <span style={{ color: '#ff4d4f' }}> *</span>}
                  <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                    ({def.type})
                  </Typography.Text>
                </Typography.Text>
                <div style={{ marginTop: 6 }}>
                  {renderField(def, formValues[def.name], (v) =>
                    setFormValues((prev) => ({ ...prev, [def.name]: v })),
                  )}
                </div>
              </div>
            ))}
            {inputDefs.length === 0 && (
              <Typography.Text type="secondary">
                该应用未声明输入变量，点击运行将以空 inputs 启动。
              </Typography.Text>
            )}
          </Space>
        )}
        <Space style={{ marginTop: 12 }}>
          <Button
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={running}
            onClick={handleRun}
          >
            {running ? '运行中…' : '运行'}
          </Button>
        </Space>
      </Card>

      {result && (
        <Card size="small" title="运行结果" style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space>
              {result.status === 'success' ? (
                <Tag icon={<CheckCircleOutlined />} color="success">
                  成功
                </Tag>
              ) : (
                <Tag icon={<PauseCircleOutlined />} color="warning">
                  待人审
                </Tag>
              )}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                run_id: {result.run_id}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                thread_id: {result.thread_id}
              </Typography.Text>
            </Space>

            {result.status === 'success' && (
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  输出：
                </Typography.Text>
                <div style={{ marginTop: 4 }}>
                  <JsonBlock value={result.output} />
                </div>
              </div>
            )}

            {result.status === 'waiting_approval' && (
              <>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    人审节点 payload：
                  </Typography.Text>
                  <div style={{ marginTop: 4 }}>
                    <JsonBlock value={result.approval} />
                  </div>
                </div>
                <Button
                  type="primary"
                  onClick={() => navigate(`/marketplace/apps/${appId}/runs`)}
                >
                  去审批
                </Button>
              </>
            )}
          </Space>
        </Card>
      )}
    </div>
  )
}
