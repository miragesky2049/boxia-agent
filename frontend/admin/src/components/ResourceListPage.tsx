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
import type { ResourceApi } from '../api/resources'
import type { ResourceBase } from '../api/types'
import { useAuth } from '../auth/AuthContext'

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

interface ResourceListPageProps<T extends ResourceBase, P> {
  title: string
  description: string
  api: ResourceApi<T, P>
  columns: ListColumn<T>[]
  fields: FormField[]
  defaults: P
  createText?: string
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
}: ResourceListPageProps<T, P>) {
  const { message } = App.useApp()
  const { canWrite } = useAuth()
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

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await api.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        is_enabled: enabledFilter === undefined ? undefined : enabledFilter === 'true',
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [api, page, pageSize, keyword, enabledFilter, message])

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

  const tableColumns: ColumnsType<T> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 220,
      render: (_: unknown, record: T) => (
        <div>
          <div className="resource-name">{record.name}</div>
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
    ...(canWrite
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 130,
            render: (_: unknown, record: T) => (
              <Space size={4}>
                <Button type="link" size="small" onClick={() => openEdit(record)}>
                  编辑
                </Button>
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
              </Space>
            ),
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
        {canWrite && (
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
    </div>
  )
}
