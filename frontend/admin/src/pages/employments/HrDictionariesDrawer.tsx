import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'
import { hrDictionariesApi, type HrDictionaryCategory } from '../../api/hrDictionary'
import type { HrDictionary } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'

const CATEGORY_LABEL: Record<HrDictionaryCategory, string> = {
  employment_type: '雇佣类型',
  job_level: '岗位职级',
  job_family: '岗位序列',
}

interface EditFormValues {
  code: string
  name: string
  sort_order: number
  remark?: string
}

interface Props {
  open: boolean
  onClose: () => void
}

export default function HrDictionariesDrawer({ open, onClose }: Props) {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canWrite = hasPermission('button:employment:update')
  const canDelete = hasPermission('button:employment:delete')

  const [category, setCategory] = useState<HrDictionaryCategory>('employment_type')
  const [items, setItems] = useState<HrDictionary[]>([])
  const [loading, setLoading] = useState(false)
  const [editing, setEditing] = useState<HrDictionary | null>(null)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm<EditFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await hrDictionariesApi.list(category, true)
      setItems(result)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '字典加载失败')
    } finally {
      setLoading(false)
    }
  }, [category, message])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const openCreate = () => {
    setCreating(true)
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ sort_order: 10, code: '', name: '', remark: '' })
  }

  const openEdit = (record: HrDictionary) => {
    setCreating(false)
    setEditing(record)
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      sort_order: record.sort_order,
      remark: record.remark || '',
    })
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    try {
      if (creating) {
        await hrDictionariesApi.create({
          category,
          code: values.code.trim(),
          name: values.name.trim(),
          sort_order: values.sort_order,
          remark: values.remark?.trim() ?? '',
        })
        message.success('字典项已创建')
      } else if (editing) {
        await hrDictionariesApi.update(editing.id, {
          name: values.name.trim(),
          sort_order: values.sort_order,
          remark: values.remark?.trim() ?? '',
        })
        message.success('字典项已更新')
      }
      setCreating(false)
      setEditing(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    }
  }

  const toggleActive = async (record: HrDictionary, isActive: boolean) => {
    try {
      await hrDictionariesApi.update(record.id, { is_active: isActive })
      message.success(isActive ? '已启用' : '已停用')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleDelete = async (record: HrDictionary) => {
    try {
      await hrDictionariesApi.remove(record.id)
      message.success('字典项已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const columns: ColumnsType<HrDictionary> = [
    {
      title: '编码',
      dataIndex: 'code',
      width: 140,
    },
    {
      title: '名称',
      dataIndex: 'name',
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      width: 90,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      render: (isActive: boolean, record) =>
        canWrite ? (
          <Switch
            size="small"
            checked={isActive}
            onChange={(value) => toggleActive(record, value)}
          />
        ) : isActive ? (
          <Tag color="green" bordered={false}>
            启用
          </Tag>
        ) : (
          <Tag color="default" bordered={false}>
            停用
          </Tag>
        ),
    },
    {
      title: '备注',
      dataIndex: 'remark',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
    ...(canWrite || canDelete
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 140,
            render: (_: unknown, record: HrDictionary) => (
              <Space size={4}>
                {canWrite && (
                  <Button type="link" size="small" onClick={() => openEdit(record)}>
                    编辑
                  </Button>
                )}
                {canDelete && (
                  <Popconfirm
                    title="确认删除该字典项？"
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
            ),
          },
        ]
      : []),
  ]

  return (
    <Drawer title="HR 字典管理" open={open} onClose={onClose} width={720} destroyOnHidden>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Segmented
            value={category}
            onChange={(value) => setCategory(value as HrDictionaryCategory)}
            options={(Object.keys(CATEGORY_LABEL) as HrDictionaryCategory[]).map((key) => ({
              label: CATEGORY_LABEL[key],
              value: key,
            }))}
          />
          {canWrite && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新建字典项
            </Button>
          )}
        </Space>
        <Table<HrDictionary>
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
          size="middle"
        />
      </Space>

      <Modal
        title={creating ? `新建${CATEGORY_LABEL[category]}` : '编辑字典项'}
        open={creating || Boolean(editing)}
        onOk={handleSubmit}
        onCancel={() => {
          setCreating(false)
          setEditing(null)
        }}
        okText={creating ? '创建' : '保存'}
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form<EditFormValues> form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="code"
            label="编码"
            rules={[
              { required: true, message: '请输入编码' },
              { pattern: /^[a-zA-Z0-9_-]{1,64}$/, message: '仅支持字母、数字、短横线、下划线' },
            ]}
            extra="编码创建后不可修改。"
          >
            <Input disabled={!creating} maxLength={64} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <InputNumber min={0} max={9999} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={255} />
          </Form.Item>
        </Form>
      </Modal>
    </Drawer>
  )
}
