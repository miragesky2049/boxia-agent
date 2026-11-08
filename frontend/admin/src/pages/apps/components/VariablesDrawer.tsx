import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Tabs,
  Tag,
  Tree,
  Typography,
  message,
} from 'antd'
import {
  getAppVariables,
  getUserVariables,
  saveAppVariables,
  saveUserVariables,
  type AppVariable,
  type AppVariableScope,
  type AppVariableType,
  type FlowType,
  type SystemVariable,
} from '../../../api/apps'
import type { NodeMeta } from '../../../api/nodeMeta'
import { listStartInputParams } from '../canvas/metadata/chatflowStart'

const VARIABLE_TYPE_OPTIONS: Array<{ value: AppVariableType; label: string }> = [
  { value: 'string', label: 'String' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'object', label: 'Object' },
  { value: 'array', label: 'Array' },
]

const SCOPE_OPTIONS: Array<{ value: AppVariableScope; label: string }> = [
  { value: 'app', label: '应用变量' },
  { value: 'user', label: '用户变量' },
]

function defaultToText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function textToDefault(text: string, type: AppVariableType): unknown {
  if (type === 'number') {
    const num = Number(text)
    return Number.isFinite(num) ? num : 0
  }
  if (type === 'boolean') return text === 'true'
  if (type === 'object' || type === 'array') {
    if (!text.trim()) return type === 'array' ? [] : {}
    try {
      return JSON.parse(text)
    } catch {
      return type === 'array' ? [] : {}
    }
  }
  return text
}

interface VariablesDrawerProps {
  open: boolean
  onClose: () => void
  applicationId?: string
  nodes: Array<{
    id: string
    typeKey: string
    title: string
    config?: Record<string, any>
  }>
  keyToMeta: Record<string, NodeMeta>
  flowType?: FlowType
}

// 变量抽屉（U-L2）：应用变量 / 用户变量 / 系统变量 / 节点输出
export function VariablesDrawer({
  open,
  onClose,
  applicationId,
  nodes,
  keyToMeta,
  flowType = 'workflow',
}: VariablesDrawerProps) {
  const [definitions, setDefinitions] = useState<AppVariable[]>([])
  const [systemVars, setSystemVars] = useState<SystemVariable[]>([])
  const [userValues, setUserValues] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [savingUser, setSavingUser] = useState(false)

  const load = useCallback(async () => {
    if (!applicationId) return
    setLoading(true)
    try {
      const data = await getAppVariables(applicationId)
      setDefinitions(data.variables ?? [])
      setSystemVars(data.system ?? [])
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载变量失败')
    } finally {
      setLoading(false)
    }
  }, [applicationId])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  const loadUserValues = useCallback(async () => {
    if (!applicationId) return
    try {
      setUserValues(await getUserVariables(applicationId))
    } catch (err) {
      message.error(err instanceof Error ? err.message : '加载用户变量失败')
    }
  }, [applicationId])

  const updateDefinition = (idx: number, patch: Partial<AppVariable>) => {
    setDefinitions((prev) => prev.map((item, i) => (i === idx ? { ...item, ...patch } : item)))
  }

  const handleSave = async () => {
    if (!applicationId) return
    setSaving(true)
    try {
      const data = await saveAppVariables(applicationId, definitions)
      setDefinitions(data.variables ?? [])
      setSystemVars(data.system ?? [])
      message.success('变量定义已保存')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存变量失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveUserValues = async () => {
    if (!applicationId) return
    setSavingUser(true)
    try {
      const values = await saveUserVariables(applicationId, userValues)
      setUserValues(values)
      message.success('当前用户变量取值已保存')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存用户变量取值失败')
    } finally {
      setSavingUser(false)
    }
  }

  const userDefinitions = useMemo(
    () => definitions.filter((item) => item.scope === 'user'),
    [definitions],
  )

  const outputTreeData = useMemo(() => {
    if (nodes.length === 0) return []
    return nodes.map((node) => {
      const meta = keyToMeta[node.typeKey]
      const outputs = (meta?.outputs || []).map((p) => ({
        key: `${node.id}.output.${p.name}`,
        title: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <code
              style={{ fontSize: 11, background: '#f3f4f6', padding: '0 4px', borderRadius: 3 }}
            >
              {p.name}
            </code>
            <span style={{ color: '#9ca3af', fontSize: 11 }}>{p.label || ''}</span>
          </span>
        ),
        isLeaf: true,
      }))
      const startInputs =
        node.typeKey === 'start'
          ? listStartInputParams(node.config?.inputs, flowType).map((inp) => ({
              key: `${node.id}.output.${inp.name}`,
              title: (
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                    入参
                  </Tag>
                  <code
                    style={{
                      fontSize: 11,
                      background: '#f3f4f6',
                      padding: '0 4px',
                      borderRadius: 3,
                    }}
                  >
                    {inp.name}
                  </code>
                </span>
              ),
              isLeaf: true,
            }))
          : []
      return {
        key: node.id,
        title: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontWeight: 500 }}>{node.title || meta?.title || node.id}</span>
            <Tag style={{ fontSize: 10, margin: 0 }} color={meta?.color || 'default'}>
              {node.typeKey}
            </Tag>
          </span>
        ),
        children: [...outputs, ...startInputs],
      }
    })
  }, [nodes, keyToMeta, flowType])

  const noApplication = !applicationId

  return (
    <Drawer title="变量" open={open} onClose={onClose} width="min(460px, 92vw)" placement="right">
      {noApplication ? (
        <Empty description="请先保存应用后再配置变量" />
      ) : (
        <Tabs
          items={[
            {
              key: 'definitions',
              label: '应用变量',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={10}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    应用变量每次运行按默认值初始化；用户变量按当前用户持久化取值。 引用方式：
                    {'{{variables.变量名}}'}
                  </Typography.Text>
                  {definitions.length === 0 && (
                    <div style={{ fontSize: 12, color: '#999' }}>暂无变量，点击下方按钮添加</div>
                  )}
                  {definitions.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        border: '1px solid #f0f0f0',
                        borderRadius: 6,
                        padding: 8,
                        background: '#fafafa',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 6,
                      }}
                    >
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <Input
                          size="small"
                          style={{ width: 140 }}
                          placeholder="变量名"
                          value={item.name}
                          onChange={(e) => updateDefinition(idx, { name: e.target.value })}
                        />
                        <Select
                          size="small"
                          style={{ width: 110 }}
                          value={item.type}
                          options={VARIABLE_TYPE_OPTIONS}
                          onChange={(type) => updateDefinition(idx, { type })}
                        />
                        <Select
                          size="small"
                          style={{ width: 110 }}
                          value={item.scope}
                          options={SCOPE_OPTIONS}
                          onChange={(scope) => updateDefinition(idx, { scope })}
                        />
                        <Button
                          size="small"
                          type="text"
                          danger
                          onClick={() => setDefinitions((prev) => prev.filter((_, i) => i !== idx))}
                        >
                          删除
                        </Button>
                      </div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <Input
                          size="small"
                          style={{ flex: 1 }}
                          placeholder="默认值"
                          value={defaultToText(item.default)}
                          onChange={(e) =>
                            updateDefinition(idx, {
                              default: textToDefault(e.target.value, item.type),
                            })
                          }
                        />
                        <Input
                          size="small"
                          style={{ flex: 1 }}
                          placeholder="描述（可选）"
                          value={item.description}
                          onChange={(e) => updateDefinition(idx, { description: e.target.value })}
                        />
                      </div>
                    </div>
                  ))}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Button
                      size="small"
                      type="dashed"
                      onClick={() =>
                        setDefinitions((prev) => [
                          ...prev,
                          { name: '', type: 'string', scope: 'app', default: '', description: '' },
                        ])
                      }
                    >
                      + 添加变量
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      loading={saving || loading}
                      onClick={handleSave}
                    >
                      保存定义
                    </Button>
                  </div>
                </Space>
              ),
            },
            {
              key: 'user-values',
              label: '用户变量取值',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={10}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    这里编辑当前登录用户的变量取值，仅影响本地调试与当前用户。
                  </Typography.Text>
                  {userDefinitions.length === 0 ? (
                    <Empty description="暂无用户作用域变量" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  ) : (
                    <>
                      {userDefinitions.map((item) => (
                        <div
                          key={item.name}
                          style={{ display: 'flex', gap: 8, alignItems: 'center' }}
                        >
                          <span style={{ width: 120, fontSize: 12, color: '#6b7280' }}>
                            {item.name}
                          </span>
                          <Input
                            size="small"
                            style={{ flex: 1 }}
                            value={defaultToText(userValues[item.name])}
                            placeholder={`默认：${defaultToText(item.default)}`}
                            onChange={(e) =>
                              setUserValues((prev) => ({
                                ...prev,
                                [item.name]: textToDefault(e.target.value, item.type),
                              }))
                            }
                          />
                        </div>
                      ))}
                      <div style={{ display: 'flex', gap: 8 }}>
                        <Button size="small" onClick={loadUserValues}>
                          加载当前值
                        </Button>
                        <Button
                          size="small"
                          type="primary"
                          loading={savingUser}
                          onClick={handleSaveUserValues}
                        >
                          保存取值
                        </Button>
                      </div>
                    </>
                  )}
                </Space>
              ),
            },
            {
              key: 'system',
              label: '系统变量',
              children: (
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    系统变量由运行入口注入，只读。引用方式：{'{{system.变量名}}'}
                  </Typography.Text>
                  {(systemVars.length > 0 ? systemVars : fallbackSystemVars(flowType)).map(
                    (item) => (
                      <div
                        key={item.name}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '6px 8px',
                          background: '#f9fafb',
                          borderRadius: 6,
                        }}
                      >
                        <Tag color="purple" style={{ fontSize: 10, margin: 0 }}>
                          系统
                        </Tag>
                        <code
                          style={{
                            fontSize: 11,
                            background: '#f3f4f6',
                            padding: '0 4px',
                            borderRadius: 3,
                          }}
                        >
                          {item.name}
                        </code>
                        <span style={{ color: '#9ca3af', fontSize: 11 }}>{item.label}</span>
                      </div>
                    ),
                  )}
                </Space>
              ),
            },
            {
              key: 'outputs',
              label: '节点输出',
              children: (
                <>
                  <div style={{ marginBottom: 12, fontSize: 12, color: '#9ca3af' }}>
                    点击字段可复制引用表达式{' '}
                    <code style={{ background: '#f3f4f6', padding: '0 4px', borderRadius: 3 }}>
                      {'{{节点ID.output.字段名}}'}
                    </code>
                  </div>
                  {outputTreeData.length === 0 ? (
                    <Empty description="画布中暂无节点" />
                  ) : (
                    <Tree
                      treeData={outputTreeData as any}
                      defaultExpandAll
                      onSelect={(keys) => {
                        const key = keys[0]
                        if (typeof key === 'string' && key.includes('.output.')) {
                          navigator.clipboard?.writeText(`{{${key}}}`).catch(() => {})
                        }
                      }}
                    />
                  )}
                </>
              ),
            },
          ]}
        />
      )}
    </Drawer>
  )
}

// 后端 system 列表为空时的本地兜底（例如接口不可达）
function fallbackSystemVars(flowType: FlowType): SystemVariable[] {
  const common: SystemVariable[] = [
    { name: 'USER_ID', label: '当前用户 ID' },
    { name: 'RUN_ID', label: '本次运行 ID' },
  ]
  if (flowType === 'chatflow') {
    return [
      { name: 'USER_INPUT', label: '本轮用户输入' },
      { name: 'CONVERSATION_NAME', label: '会话名称' },
      { name: 'CONVERSATION_ID', label: '会话 ID' },
      ...common,
    ]
  }
  return common
}
