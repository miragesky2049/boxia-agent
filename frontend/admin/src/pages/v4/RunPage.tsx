import {
  CheckCircleOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import { App, Button, Card, Empty, Input, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  listMyApps,
  runApplication,
  type V4MyApp,
  type V4RunResult,
} from '../../api/v4'

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

export default function V4RunPage() {
  const { appId } = useParams<{ appId: string }>()
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [app, setApp] = useState<V4MyApp | null>(null)
  const [loadingApp, setLoadingApp] = useState(true)
  const [inputsText, setInputsText] = useState('{\n\n}')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<V4RunResult | null>(null)

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

  const handleRun = async () => {
    if (!appId) return
    let inputs: Record<string, unknown> = {}
    const trimmed = inputsText.trim()
    if (trimmed) {
      try {
        const parsed = JSON.parse(trimmed)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          inputs = parsed as Record<string, unknown>
        } else {
          message.error('inputs 必须是 JSON 对象')
          return
        }
      } catch (error) {
        message.error(`inputs JSON 解析失败：${error instanceof Error ? error.message : '格式错误'}`)
        return
      }
    }
    setRunning(true)
    setResult(null)
    try {
      const res = await runApplication(appId, inputs)
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

  if (loadingApp) {
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
        <Button onClick={() => navigate(`/v4/marketplace/apps/${appId}/runs`)}>
          查看运行历史
        </Button>
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        {app.description || '暂无描述'}
      </Typography.Paragraph>

      <Card size="small" title="输入参数（JSON 对象）" style={{ marginTop: 16 }}>
        <Input.TextArea
          value={inputsText}
          onChange={(e) => setInputsText(e.target.value)}
          rows={8}
          style={{ fontFamily: 'monospace', fontSize: 13 }}
          placeholder='例如：{"query": "查一下快递 SF123456"}'
        />
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
                  onClick={() => navigate(`/v4/marketplace/apps/${appId}/runs`)}
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
