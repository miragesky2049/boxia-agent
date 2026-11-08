import { useCallback, useEffect, useRef, useState } from 'react'
import { App, Button, Drawer, Form, Input, Modal, Popconfirm, Space, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  addCase,
  createDataset,
  deleteCase,
  deleteDataset,
  listCases,
  listDatasets,
  type EvalCase,
  type EvalDataset,
} from '../../../api/eval'

interface DatasetsPanelProps {
  applicationId: string
}

/**
 * 数据集页签：列表 + 新建 + 用例管理抽屉（F18.1/F18.2）。
 * 用例 input 固定 {message} 形态，与 worker 直调侧 _CaseInputRunner 消费口径一致。
 */
export default function DatasetsPanel({ applicationId }: DatasetsPanelProps) {
  const { message } = App.useApp()
  // null=加载中；数据只在请求回调里落 state，避免 effect 同步 setState 级联渲染
  const [items, setItems] = useState<EvalDataset[] | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm()

  const [activeDataset, setActiveDataset] = useState<EvalDataset | null>(null)
  const [cases, setCases] = useState<EvalCase[] | null>(null)
  const casesSeq = useRef(0)
  const [caseForm] = Form.useForm()

  const load = useCallback(() => {
    listDatasets(applicationId)
      .then(setItems)
      .catch((err: Error) => {
        message.error(err.message)
        setItems([])
      })
  }, [applicationId, message])

  useEffect(() => {
    load()
  }, [load])

  const loadCases = useCallback(
    (datasetId: string) => {
      // 请求序号守卫：先开 A 抽屉再快速开 B 时，A 的慢响应不得覆盖 B 的用例
      const seq = ++casesSeq.current
      setCases(null)
      listCases(datasetId)
        .then((rows) => {
          if (seq === casesSeq.current) setCases(rows)
        })
        .catch((err: Error) => {
          if (seq !== casesSeq.current) return
          message.error(err.message)
          setCases([])
        })
    },
    [message],
  )

  const handleCreate = async () => {
    let values: { name: string; description?: string }
    try {
      values = await form.validateFields()
    } catch (error) {
      // 字段校验失败时表单项已有内联错误提示，静默返回（同 AppListPage 先例）
      if (error && (error as { errorFields?: unknown }).errorFields) return
      message.error(error instanceof Error ? error.message : '校验数据集表单失败')
      return
    }
    setSubmitting(true)
    try {
      await createDataset({
        application_id: applicationId,
        name: values.name,
        description: values.description ?? '',
      })
      message.success('数据集已创建')
      setCreateOpen(false)
      form.resetFields()
      load()
    } catch (err) {
      message.error((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleDelete = async (datasetId: string) => {
    try {
      await deleteDataset(datasetId)
      load()
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const openCases = (dataset: EvalDataset) => {
    setActiveDataset(dataset)
    loadCases(dataset.id)
  }

  const handleAddCase = async () => {
    if (!activeDataset) return
    let values: { message: string; expected?: string }
    try {
      values = await caseForm.validateFields()
    } catch (error) {
      if (error && (error as { errorFields?: unknown }).errorFields) return
      message.error(error instanceof Error ? error.message : '校验用例表单失败')
      return
    }
    try {
      await addCase(activeDataset.id, { input: { message: values.message }, expected: values.expected || null })
      caseForm.resetFields()
      loadCases(activeDataset.id)
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const handleDeleteCase = async (caseId: string) => {
    if (!activeDataset) return
    try {
      await deleteCase(caseId)
      loadCases(activeDataset.id)
    } catch (err) {
      message.error((err as Error).message)
    }
  }

  const columns: ColumnsType<EvalDataset> = [
    { title: '名称', dataIndex: 'name' },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '操作',
      key: 'actions',
      width: 180,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openCases(record)}>
            用例管理
          </Button>
          <Popconfirm title="删除数据集会同时删除其用例，确认？" onConfirm={() => void handleDelete(record.id)}>
            <Button type="link" size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const caseColumns: ColumnsType<EvalCase> = [
    {
      title: '问句',
      dataIndex: 'input',
      render: (input: Record<string, unknown>) => String(input.message ?? ''),
    },
    { title: '期望答案', dataIndex: 'expected', render: (v: string | null) => v ?? '—' },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_, record) => (
        <Button type="link" size="small" danger onClick={() => void handleDeleteCase(record.id)}>
          删除
        </Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space>
        <Button type="primary" onClick={() => setCreateOpen(true)}>
          新建数据集
        </Button>
      </Space>
      <Table rowKey="id" loading={items === null} columns={columns} dataSource={items ?? []} size="small" pagination={false} />

      <Modal
        title="新建数据集"
        open={createOpen}
        okText="创建"
        confirmLoading={submitting}
        onOk={() => void handleCreate()}
        onCancel={() => {
          setCreateOpen(false)
          form.resetFields()
        }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入数据集名称' }]}>
            <Input placeholder="数据集名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="描述（选填）" rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={activeDataset ? `用例管理 - ${activeDataset.name}` : '用例管理'}
        open={activeDataset !== null}
        width={720}
        onClose={() => {
          // 关闭抽屉即作废在途用例请求，避免慢响应落到下次打开的抽屉
          casesSeq.current += 1
          setActiveDataset(null)
        }}
        extra={
          <Button type="primary" size="small" onClick={() => caseForm.submit()}>
            新增用例
          </Button>
        }
      >
        <Form form={caseForm} layout="inline" style={{ marginBottom: 16 }} onFinish={() => void handleAddCase()}>
          <Form.Item name="message" rules={[{ required: true, message: '请输入问句' }]} style={{ flex: 1 }}>
            <Input placeholder="请输入用户问句" />
          </Form.Item>
          <Form.Item name="expected" style={{ flex: 1 }}>
            <Input placeholder="期望答案（选填）" />
          </Form.Item>
        </Form>
        <Table rowKey="id" loading={cases === null} columns={caseColumns} dataSource={cases ?? []} size="small" pagination={false} />
      </Drawer>
    </Space>
  )
}
