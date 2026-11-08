import { useCallback, useEffect, useState } from 'react'
import { App, Button, Form, Input, Modal, Popconfirm, Select, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  createEvaluator,
  deleteEvaluator,
  listEvaluators,
  updateEvaluator,
  type EvalEvaluator,
} from '../../../api/eval'

const TYPE_OPTIONS = [
  { value: 'rule', label: '规则断言' },
  { value: 'llm_judge', label: 'LLM 判定' },
]

/**
 * 评估器页签：rule 纯代码断言 / llm_judge 唯一判定内核（F19），config 为 JSON 文本录入。
 */
export default function EvaluatorsPanel() {
  const { message } = App.useApp()
  // null=加载中；数据只在请求回调里落 state，避免 effect 同步 setState 级联渲染
  const [items, setItems] = useState<EvalEvaluator[] | null>(null)
  const [editing, setEditing] = useState<EvalEvaluator | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [configError, setConfigError] = useState<string | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(() => {
    listEvaluators()
      .then(setItems)
      .catch((err: Error) => {
        message.error(err.message)
        setItems([])
      })
  }, [message])

  useEffect(() => {
    load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    setConfigError(null)
    form.resetFields()
    setModalOpen(true)
    // Modal 未打开时 Form 未挂载，延后 setFieldsValue 避免 antd not-connected 告警（同 AppListPage 先例）
    requestAnimationFrame(() => {
      form.setFieldsValue({ type: 'rule', config: '{}' })
    })
  }

  const openEdit = (record: EvalEvaluator) => {
    setEditing(record)
    setConfigError(null)
    setModalOpen(true)
    requestAnimationFrame(() => {
      form.setFieldsValue({
        name: record.name,
        type: record.type,
        config: JSON.stringify(record.config ?? {}),
      })
    })
  }

  const handleSave = async () => {
    let values: { name: string; type: 'rule' | 'llm_judge'; config?: string }
    try {
      values = await form.validateFields()
    } catch (error) {
      // 字段校验失败时表单项已有内联错误提示，静默返回（同 AppListPage 先例）
      if (error && (error as { errorFields?: unknown }).errorFields) return
      message.error(error instanceof Error ? error.message : '校验评估器表单失败')
      return
    }
    let config: Record<string, unknown>
    try {
      config = values.config?.trim() ? JSON.parse(values.config) : {}
    } catch {
      setConfigError('配置必须是合法 JSON')
      return
    }
    setConfigError(null)
    const payload = { name: values.name, type: values.type, config }
    setSubmitting(true)
    try {
      if (editing) {
        await updateEvaluator(editing.id, payload)
      } else {
        await createEvaluator(payload)
      }
      message.success('评估器已保存')
      setModalOpen(false)
      load()
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteEvaluator(id)
      load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const columns: ColumnsType<EvalEvaluator> = [
    { title: '名称', dataIndex: 'name' },
    {
      title: '类型',
      dataIndex: 'type',
      width: 120,
      render: (type: string) => TYPE_OPTIONS.find((t) => t.value === type)?.label ?? type,
    },
    {
      title: '配置',
      dataIndex: 'config',
      ellipsis: true,
      render: (config: Record<string, unknown>) => JSON.stringify(config ?? {}),
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该评估器？" onConfirm={() => void handleDelete(record.id)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Button type="primary" onClick={openCreate}>
        新建评估器
      </Button>
      <Table
        rowKey="id"
        loading={items === null}
        columns={columns}
        dataSource={items ?? []}
        size="small"
        pagination={false}
      />

      <Modal
        title={editing ? '编辑评估器' : '新建评估器'}
        open={modalOpen}
        okText="保存"
        confirmLoading={submitting}
        onOk={() => void handleSave()}
        onCancel={() => setModalOpen(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: '请输入评估器名称' }]}
          >
            <Input placeholder="评估器名称" />
          </Form.Item>
          <Form.Item name="type" label="类型" rules={[{ required: true }]}>
            <Select options={TYPE_OPTIONS} />
          </Form.Item>
          <Form.Item name="config" label="配置">
            <Input.TextArea placeholder="配置 JSON" rows={4} />
          </Form.Item>
          {configError ? <div style={{ color: '#ff4d4f' }}>{configError}</div> : null}
        </Form>
      </Modal>
    </Space>
  )
}
