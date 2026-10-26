import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { listAgents } from '../api/agents'
import type { ResourceApi } from '../api/resources'
import type { AgentSummary, ResourceBase, ResourceType } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import AuthorizationDrawer from './AuthorizationDrawer'

export type FormFieldType = 'text' | 'textarea' | 'switch' | 'select' | 'tags' | 'json' | 'number'

export interface FormField {
  name: string
  label: string
  type?: FormFieldType
  required?: boolean
  placeholder?: string
  options?: { label: string; value: string }[]
  rows?: number
  min?: number
  max?: number
  extra?: string
}

export interface ListColumn<T> {
  title: string
  key: string
  width?: number
  render?: (record: T) => ReactNode
}

export interface RowActionHelpers {
  /** 重新加载当前列表，自定义操作改动数据后调用。 */
  reload: () => Promise<void>
}

interface ResourceListPageProps<T extends ResourceBase, P> {
  title: string
  description: string
  api: ResourceApi<T, P>
  columns: ListColumn<T>[]
  fields: FormField[]
  defaults: P
  createText?: string
  /** 固定归属智能体：列表按该智能体过滤，新建时自动写入归属。 */
  agentId?: string
  /** 资源类型；克隆操作需要它定位资源接口。 */
  resourceType?: ResourceType
  /** 是否展示克隆到其他智能体的操作。 */
  enableClone?: boolean
  /** 行级自定义操作，渲染在编辑/删除之前；只读角色也会展示。 */
  extraActions?: (record: T, helpers: RowActionHelpers) => ReactNode
}

type FormValue = string | number | boolean | string[] | Record<string, unknown>
type FormValues = Record<string, FormValue>

function toFormValues(source: Record<string, unknown>, fields: FormField[]): FormValues {
  const values = { ...source } as FormValues
  for (const field of fields) {
    if (field.type === 'json' && values[field.name] && typeof values[field.name] === 'object') {
      values[field.name] = JSON.stringify(values[field.name], null, 2)
    }
  }
  return values
}

export default function ResourceListPage<T extends ResourceBase, P>({
  title,
  description,
  api,
  columns,
  fields,
  defaults,
  createText = '新建',
  agentId,
  resourceType,
  enableClone = false,
  extraActions,
}: ResourceListPageProps<T, P>) {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = resourceType ? hasPermission(`button:${resourceType}:create`) : false
  const canUpdate = resourceType ? hasPermission(`button:${resourceType}:update`) : false
  const canDelete = resourceType ? hasPermission(`button:${resourceType}:delete`) : false
  const canEdit = canUpdate || canDelete
  const { isPlatform } = useTenant()
  const [form] = Form.useForm<FormValues>()
  const [items, setItems] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [enabledFilter, setEnabledFilter] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<T | null>(null)
  const [saving, setSaving] = useState(false)
  const [cloneSource, setCloneSource] = useState<T | null>(null)
  const [cloneAgents, setCloneAgents] = useState<AgentSummary[]>([])
  const [cloning, setCloning] = useState(false)
  const [grantTarget, setGrantTarget] = useState<T | null>(null)
  const [cloneForm] = Form.useForm<{ agent_id: string; name?: string }>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await api.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        is_enabled: enabledFilter === undefined ? undefined : enabledFilter === 'true',
        agent_id: agentId,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [api, page, pageSize, keyword, enabledFilter, agentId, message])

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue(toFormValues(defaults as FormValues, fields))
    setModalOpen(true)
  }

  const openEdit = (record: T) => {
    setEditing(record)
    form.setFieldsValue(toFormValues(record as unknown as FormValues, fields))
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    const payload: Record<string, unknown> = { ...(defaults as FormValues), ...values }
    // 智能体详情内创建的资源必须绑定归属智能体
    if (agentId !== undefined && !editing) payload.agent_id = agentId
    for (const field of fields) {
      if (field.type === 'json' && typeof payload[field.name] === 'string') {
        const raw = (payload[field.name] as string).trim()
        try {
          payload[field.name] = raw ? JSON.parse(raw) : {}
        } catch {
          message.error(`${field.label} 不是合法的 JSON`)
          return
        }
      }
    }

    setSaving(true)
    try {
      if (editing) {
        await api.update(editing.id, payload as P)
        message.success('保存成功')
      } else {
        await api.create(payload as P)
        message.success('创建成功')
      }
      setModalOpen(false)
      setEditing(null)
      form.resetFields()
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (record: T) => {
    try {
      await api.remove(record.id)
      message.success('已删除')
      if (items.length === 1 && page > 1) {
        setPage(page - 1)
      } else {
        await load()
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const openClone = async (record: T) => {
    setCloneSource(record)
    cloneForm.setFieldsValue({ agent_id: undefined, name: undefined })
    try {
      const result = await listAgents({ page: 1, page_size: 100 })
      setCloneAgents(result.items)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载智能体失败')
    }
  }

  const handleClone = async () => {
    if (!cloneSource || !resourceType) return
    const values = await cloneForm.validateFields()
    setCloning(true)
    try {
      await api.clone(cloneSource.id, {
        agent_id: values.agent_id,
        name: values.name?.trim() || null,
      })
      message.success('克隆成功，副本与原资源相互独立')
      setCloneSource(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '克隆失败')
    } finally {
      setCloning(false)
    }
  }

  const showExtraActions = Boolean(resourceType || enableClone || extraActions)

  const tableColumns: ColumnsType<T> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: (_: unknown, record: T) => (
        <div>
          <div className="resource-name">
            {record.name}
            {record.is_platform ? (
              <Tag color="geekblue" bordered={false} style={{ marginLeft: 8 }}>
                平台级
              </Tag>
            ) : (
              !isPlatform && (
                <Tag color="green" bordered={false} style={{ marginLeft: 8 }}>
                  本租户
                </Tag>
              )
            )}
          </div>
          {record.description && <div className="resource-desc">{record.description}</div>}
        </div>
      ),
    },
    ...columns.map((column) => ({
      title: column.title,
      key: column.key,
      width: column.width,
      render: (_: unknown, record: T) =>
        column.render
          ? column.render(record)
          : String((record as unknown as Record<string, unknown>)[column.key] ?? ''),
    })),
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 90,
      render: (enabled: boolean) => (enabled ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    ...(canEdit || showExtraActions || (isPlatform && resourceType)
      ? [
          {
            title: '操作',
            key: 'actions',
            width: showExtraActions ? 320 : 130,
            render: (_: unknown, record: T) => {
              const readonly = record.is_platform && !isPlatform
              return (
                <Space size={4} wrap>
                  {extraActions?.(record, { reload: load })}
                  {isPlatform && resourceType && (
                    <Button type="link" size="small" onClick={() => setGrantTarget(record)}>
                      授权
                    </Button>
                  )}
                  {resourceType && enableClone && canCreate && (
                    <Button type="link" size="small" onClick={() => void openClone(record)}>
                      克隆
                    </Button>
                  )}
                  {readonly && canEdit && <Tag bordered={false}>产品级资源只读</Tag>}
                  {!readonly && canUpdate && (
                    <Button type="link" size="small" onClick={() => openEdit(record)}>
                      编辑
                    </Button>
                  )}
                  {!readonly && canDelete && (
                    <Popconfirm
                      title="确认删除？"
                      description="删除后不可恢复。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDelete(record)}
                    >
                      <Button type="link" size="small" danger>
                        删除
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              )
            },
          },
        ]
      : []),
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">{title}</h2>
          <p className="page-header__desc">{description}</p>
        </div>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {createText}
          </Button>
        )}
      </div>

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索名称或描述"
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 130 }}
          value={enabledFilter}
          options={[
            { label: '启用', value: 'true' },
            { label: '停用', value: 'false' },
          ]}
          onChange={(value) => {
            setEnabledFilter(value)
            setPage(1)
          }}
        />
      </div>

      <Table<T>
        rowKey="id"
        columns={tableColumns}
        dataSource={items}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (count) => `共 ${count} 条`,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
      />

      <Modal
        title={editing ? `编辑${title.replace('管理', '')}` : createText}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => {
          setModalOpen(false)
          setEditing(null)
        }}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        forceRender
        width={640}
      >
        <Form form={form} layout="vertical" className="resource-form">
          {fields.map((field) => {
            const type = field.type ?? 'text'
            const rules = field.required
              ? [{ required: true, message: `请输入${field.label}` }]
              : []
            const control =
              type === 'textarea' ? (
                <Input.TextArea rows={field.rows ?? 4} placeholder={field.placeholder} />
              ) : type === 'json' ? (
                <Input.TextArea
                  rows={field.rows ?? 6}
                  placeholder={field.placeholder ?? '{}'}
                  className="code-textarea"
                />
              ) : type === 'select' ? (
                <Select options={field.options} placeholder={field.placeholder} />
              ) : type === 'tags' ? (
                <Select mode="tags" placeholder={field.placeholder} />
              ) : type === 'number' ? (
                <InputNumber
                  style={{ width: '100%' }}
                  min={field.min}
                  max={field.max}
                  placeholder={field.placeholder}
                />
              ) : type === 'switch' ? (
                <Switch />
              ) : (
                <Input placeholder={field.placeholder} />
              )

            return (
              <Form.Item
                key={field.name}
                name={field.name}
                label={field.label}
                rules={rules}
                valuePropName={type === 'switch' ? 'checked' : 'value'}
                extra={field.extra}
              >
                {control}
              </Form.Item>
            )
          })}
        </Form>
      </Modal>

      <Modal
        title={`克隆${title.replace('管理', '')}`}
        open={cloneSource !== null}
        onOk={handleClone}
        onCancel={() => setCloneSource(null)}
        confirmLoading={cloning}
        okText="克隆"
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form form={cloneForm} layout="vertical">
          <Form.Item
            name="agent_id"
            label="目标智能体"
            rules={[{ required: true, message: '请选择目标智能体' }]}
            extra="克隆会生成独立副本，之后修改互不影响。"
          >
            <Select
              placeholder="选择目标智能体"
              options={cloneAgents.map((agent) => ({ label: agent.name, value: agent.id }))}
            />
          </Form.Item>
          <Form.Item name="name" label="副本名称" extra="留空时自动使用“原名（副本）”。">
            <Input placeholder="可选" maxLength={100} />
          </Form.Item>
        </Form>
      </Modal>

      {isPlatform && resourceType && grantTarget && (
        <AuthorizationDrawer
          open={grantTarget !== null}
          onClose={() => setGrantTarget(null)}
          onSaved={() => void load()}
          resourceType={resourceType}
          resourceId={grantTarget.id}
          resourceName={grantTarget.name}
        />
      )}
    </div>
  )
}
