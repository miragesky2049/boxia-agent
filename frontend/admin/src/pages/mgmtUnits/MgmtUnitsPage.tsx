import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  TreeSelect,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mgmtUnitsApi } from '../../api/mgmtUnit'
import type { MgmtUnit } from '../../api/mgmtUnit'
import { useAuth } from '../../auth/AuthContext'

interface MgmtUnitFormValues {
  parent_id?: string | null
  name: string
  code?: string | null
  sort_order: number
  is_active?: boolean
}

const MAX_LEVEL = 10

function flatten(units: MgmtUnit[], depth = 0): MgmtUnit[] {
  return units.flatMap((unit) => [
    { ...unit, level: depth + 1 },
    ...flatten(unit.children ?? [], depth + 1),
  ])
}

function buildTreeData(
  units: MgmtUnit[],
  maxLevel: number,
): { value: string; title: string; children?: ReturnType<typeof buildTreeData> }[] {
  return units
    .filter((unit) => unit.level < maxLevel)
    .map((unit) => ({
      value: unit.id,
      title: `${'　'.repeat(unit.level - 1)}${unit.name}`,
      children: unit.children ? buildTreeData(unit.children, maxLevel) : undefined,
    }))
}

export default function MgmtUnitsPage() {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const navigate = useNavigate()
  const canCreate = hasPermission('button:mgmt-unit:create')
  const canUpdate = hasPermission('button:mgmt-unit:update')
  const canDelete = hasPermission('button:mgmt-unit:delete')

  const [tree, setTree] = useState<MgmtUnit[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<MgmtUnit | null>(null)
  const [form] = Form.useForm<MgmtUnitFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTree(await mgmtUnitsApi.tree())
    } catch (error) {
      message.error(error instanceof Error ? error.message : '管理单元加载失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
  }, [load])

  const flatUnits = useMemo(() => flatten(tree), [tree])
  const parentTreeData = useMemo(() => buildTreeData(tree, MAX_LEVEL - 1), [tree])

  const openCreate = (parentId: string | null) => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({
      parent_id: parentId,
      sort_order: 0,
      is_active: true,
    })
    setModalOpen(true)
  }

  const openEdit = (unit: MgmtUnit) => {
    setEditing(unit)
    form.resetFields()
    form.setFieldsValue({
      parent_id: unit.parent_id,
      name: unit.name,
      code: unit.code ?? undefined,
      sort_order: unit.sort_order,
      is_active: unit.is_active,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await mgmtUnitsApi.update(editing.id, {
          parent_id: values.parent_id ?? null,
          name: values.name,
          code: values.code || null,
          sort_order: values.sort_order,
          attrs: {},
          is_active: values.is_active ?? true,
        })
        message.success('管理单元已更新')
        setModalOpen(false)
        void load()
      } else {
        const created = await mgmtUnitsApi.create({
          parent_id: values.parent_id ?? null,
          name: values.name,
          code: values.code || null,
          sort_order: values.sort_order,
          attrs: {},
        })
        message.success('管理单元已创建')
        setModalOpen(false)
        navigate(`/mgmt-units/${created.id}`)
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (unit: MgmtUnit) => {
    try {
      await mgmtUnitsApi.remove(unit.id)
      message.success('管理单元已删除')
      void load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const columns: ColumnsType<MgmtUnit> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, unit) => (
        <span>
          {'　'.repeat(unit.level - 1)}
          <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/mgmt-units/${unit.id}`)}>
            {text}
          </Button>
        </span>
      ),
    },
    { title: '编码', dataIndex: 'code', key: 'code', width: 140, render: (code: string | null) => code || '-' },
    { title: '排序', dataIndex: 'sort_order', key: 'sort_order', width: 80 },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 90,
      render: (active: boolean) =>
        active ? <Tag color="green">启用</Tag> : <Tag color="red">停用</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 220,
      render: (_, unit) => (
        <Space>
          {canCreate && unit.level < MAX_LEVEL && (
            <Button size="small" onClick={() => openCreate(unit.id)}>
              新增下级
            </Button>
          )}
          {canUpdate && (
            <Button size="small" onClick={() => openEdit(unit)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm
              title={`确认删除管理单元 ${unit.name}？`}
              onConfirm={() => handleDelete(unit)}
            >
              <Button size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate(null)}>
            新建管理单元
          </Button>
        )}
      </Space>
      <Table
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={flatUnits}
        pagination={false}
      />
      <Modal
        open={modalOpen}
        title={editing ? '编辑管理单元' : '新建管理单元'}
        onCancel={() => setModalOpen(false)}
        onOk={() => void handleSubmit()}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item label="上级单元" name="parent_id">
            <TreeSelect allowClear treeData={parentTreeData} placeholder="留空表示根单元" />
          </Form.Item>
          <Form.Item label="名称" name="name" rules={[{ required: true, max: 100 }]}>
            <Input />
          </Form.Item>
          <Form.Item label="编码" name="code" tooltip="小写字母/数字/下划线/短横线，可选">
            <Input />
          </Form.Item>
          <Form.Item label="排序" name="sort_order" rules={[{ required: true }]}>
            <InputNumber min={0} max={999999} />
          </Form.Item>
          {editing && (
            <Form.Item label="启用" name="is_active" valuePropName="checked">
              <Switch />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  )
}
