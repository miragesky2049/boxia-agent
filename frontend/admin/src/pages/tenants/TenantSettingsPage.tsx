import { ArrowLeftOutlined, SaveOutlined } from '@ant-design/icons'
import { App, Button, Card, Form, Input, Select, Space, Spin, Switch, Tag, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { listAvailableModels, type ModelCatalogItem } from '../../api/models'
import { getTenantSettings, updateTenantSettings } from '../../api/tenantSettings'
import { getTenant } from '../../api/tenant'

interface FormState {
  default_model_catalog_id: string | null
  allowed_catalog_ids: string[]
  use_whitelist: boolean
  plugin_whitelist: string[]
  plugin_input: string
}

export default function TenantSettingsPage() {
  const { id } = useParams<{ id: string }>()
  const tenantId = id ?? ''
  const navigate = useNavigate()
  const { message } = App.useApp()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [tenantName, setTenantName] = useState('')
  const [catalogs, setCatalogs] = useState<ModelCatalogItem[]>([])
  const [form, setForm] = useState<FormState>({
    default_model_catalog_id: null,
    allowed_catalog_ids: [],
    use_whitelist: false,
    plugin_whitelist: [],
    plugin_input: '',
  })

  // catalog 接口返回的是 model_id，不是 catalog.id；这里只能按 model_id 选择
  // 为了 T16 可用，前端先按 model_id 直选（后端 list_catalog 也返回 model_id 主键）
  // 后端 allowed_catalog_ids 存的是 catalog UUID；这里简化为：直接使用 model_id 字符串作为标识
  // 实际生产用 admin/list_catalog 全量接口返回的 id 字段（后续接入）

  const load = useCallback(async () => {
    if (!tenantId) return
    setLoading(true)
    try {
      const [tenant, settings, modelList] = await Promise.all([
        getTenant(tenantId),
        getTenantSettings(tenantId),
        listAvailableModels().catch(() => [] as ModelCatalogItem[]),
      ])
      setTenantName(tenant.name)
      setCatalogs(modelList)
      setForm({
        default_model_catalog_id: settings.default_model_catalog_id,
        allowed_catalog_ids: settings.allowed_catalog_ids,
        use_whitelist: settings.allowed_catalog_ids.length > 0,
        plugin_whitelist: settings.plugin_whitelist,
        plugin_input: '',
      })
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载租户配置失败')
    } finally {
      setLoading(false)
    }
  }, [tenantId, message])

  useEffect(() => {
    void load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    try {
      const payload = {
        default_model_catalog_id: form.default_model_catalog_id,
        allowed_catalog_ids: form.use_whitelist ? form.allowed_catalog_ids : [],
        plugin_whitelist: form.plugin_whitelist,
      }
      await updateTenantSettings(tenantId, payload)
      message.success('租户配置已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const addPlugin = () => {
    const name = form.plugin_input.trim()
    if (!name) return
    if (form.plugin_whitelist.includes(name)) {
      message.warning('插件已存在')
      return
    }
    setForm({ ...form, plugin_whitelist: [...form.plugin_whitelist, name], plugin_input: '' })
  }

  return (
    <div className="page-card">
      <div className="page-header">
        <Space size={12} align="center">
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate(`/tenants/${tenantId}`)}
          />
          <div>
            <h2 className="page-header__title">租户运行时配置 · {tenantName || tenantId}</h2>
            <p className="page-header__desc">默认模型 / 模型白名单 / 插件白名单</p>
          </div>
        </Space>
      </div>

      <Spin spinning={loading}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Card title="默认模型" size="small">
            <Form layout="vertical">
              <Form.Item label="默认模型（画布新建 LLM 节点时的默认值）">
                <Select
                  allowClear
                  placeholder="不指定则走平台默认"
                  value={form.default_model_catalog_id ?? undefined}
                  onChange={(value) =>
                    setForm({ ...form, default_model_catalog_id: value ?? null })
                  }
                  options={catalogs.map((c) => ({
                    value: c.model_id,
                    label: `${c.display_name || c.model_id}（${c.provider_name}）`,
                  }))}
                />
              </Form.Item>
            </Form>
          </Card>

          <Card title="模型白名单" size="small">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Space>
                <Switch
                  checked={form.use_whitelist}
                  onChange={(checked) => setForm({ ...form, use_whitelist: checked })}
                />
                <Typography.Text>
                  {form.use_whitelist
                    ? '已启用白名单（仅下列模型对租户可见）'
                    : '未启用（平台全量可见）'}
                </Typography.Text>
              </Space>
              {form.use_whitelist && (
                <Select
                  mode="multiple"
                  placeholder="选择允许的模型"
                  value={form.allowed_catalog_ids}
                  onChange={(value) => setForm({ ...form, allowed_catalog_ids: value })}
                  options={catalogs.map((c) => ({
                    value: c.model_id,
                    label: `${c.display_name || c.model_id}（${c.provider_name}）`,
                  }))}
                />
              )}
            </Space>
          </Card>

          <Card title="插件白名单" size="small">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Typography.Text type="secondary">
                允许该租户调用的工具名列表；空列表表示平台全量可见。
              </Typography.Text>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="工具名，例如 get_weather"
                  value={form.plugin_input}
                  onChange={(e) => setForm({ ...form, plugin_input: e.target.value })}
                  onPressEnter={addPlugin}
                />
                <Button onClick={addPlugin}>添加</Button>
              </Space.Compact>
              <Space wrap>
                {form.plugin_whitelist.map((name) => (
                  <Tag
                    key={name}
                    closable
                    onClose={() =>
                      setForm({
                        ...form,
                        plugin_whitelist: form.plugin_whitelist.filter((x) => x !== name),
                      })
                    }
                  >
                    {name}
                  </Tag>
                ))}
                {form.plugin_whitelist.length === 0 && (
                  <Typography.Text type="secondary">尚未配置白名单</Typography.Text>
                )}
              </Space>
            </Space>
          </Card>

          <Space>
            <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
              保存配置
            </Button>
            <Button onClick={() => navigate(`/tenants/${tenantId}`)}>返回</Button>
          </Space>
        </Space>
      </Spin>
    </div>
  )
}
