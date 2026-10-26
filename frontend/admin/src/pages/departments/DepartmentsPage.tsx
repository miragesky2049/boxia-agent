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
import { departmentsApi } from '../../api/department'
import type { Department } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { buildDepartmentTreeData, flattenDepartments } from '../../utils/departmentTree'

interface DepartmentFormValues {
  parent_id?: string | null
  name: string
  code?: string
  sort_order: number
  is_active?: boolean
}

const MAX_LEVEL = 10

export default function DepartmentsPage() {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = hasPermission('button:department:create')
  const canUpdate = hasPermission('button:department:update')
  const canDelete = hasPermission('button:department:delete')

  const [tree, setTree] = useState<Department[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Department | null>(null)
  const [presetParentId, setPresetParentId] = useState<string | null>(null)
  const [form] = Form.useForm<DepartmentFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTree(await departmentsApi.tree())
    } catch (error) {
      message.error(error instanceof Error ? error.message : '部门加载失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
  }, [load])

  const flatDepartments = useMemo(() => flattenDepartments(tree), [tree])
  // 数据异步到达，defaultExpandAllRows 只在首次挂载生效；用受控展开默认全量展开，同时允许手动收起
  const [collapsedKeys, setCollapsedKeys] = useState<ReadonlySet<string>>(new Set())
  const expandedRowKeys = useMemo(
    () => flatDepartments.filter((item) => !collapsedKeys.has(item.id)).map((item) => item.id),
    [flatDepartments, collapsedKeys],
  )
  const parentTreeData = useMemo(
    () => buildDepartmentTreeData(tree, MAX_LEVEL - 1, true),
    [tree],
  )

  const openCreate = (parentId: string | null) => {
    setEditing(null)
    setPresetParentId(parentId)
    form.resetFields()
    form.setFieldsValue({
      parent_id: parentId,
      name: '',
      code: undefined,
      sort_order: 0,
      is_active: true,
    })
    setModalOpen(true)
  }

  const openEdit = (record: Department) => {
    setEditing(record)
    setPresetParentId(null)
    form.setFieldsValue({
      parent_id: record.parent_id,
      name: record.name,
      code: record.code ?? undefined,
      sort_order: record.sort_order,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await departmentsApi.update(editing.id, {
          parent_id: values.parent_id ?? null,
          name: values.name.trim(),
          code: values.code?.trim() ? values.code.trim() : null,
          sort_order: values.sort_order,
        })
        message.success('已保存')
      } else {
        await departmentsApi.create({
          parent_id: values.parent_id ?? null,
          name: values.name.trim(),
          code: values.code?.trim() ? values.code.trim() : null,
          sort_order: values.sort_order,
          is_active: values.is_active ?? true,
        })
        message.success('部门已创建')
      }
      setModalOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleActive = async (record: Department, active: boolean) => {
    try {
      await departmentsApi.setActive(record.id, active)
      message.success(active ? '部门已启用' : '部门已停用')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleDelete = async (record: Department) => {
    try {
      await departmentsApi.remove(record.id)
      message.success('部门已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  // 编辑时禁选被移动节点自身及其下级，避免前端选出成环的父级
  const editableTreeData = useMemo(() => {
    if (!editing) return parentTreeData
    const blockedPrefix = editing.path
    const filterNode = (
      nodes: ReturnType<typeof buildDepartmentTreeData>,
    ): ReturnType<typeof buildDepartmentTreeData> =>
      nodes.flatMap((node) => {
        const department = flatDepartments.find((item) => item.id === node.value)
        if (department && department.path.startsWith(blockedPrefix)) {
          return []
        }
        const next = node.children ? filterNode(node.children) : undefined
        return [{ ...node, children: next && next.length > 0 ? next : undefined }]
      })
    return filterNode(parentTreeData)
  }, [editing, flatDepartments, parentTreeData])

  const columns: ColumnsType<Department> = [
    {
      title: '部门名称',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, record: Department) => (
        <Space size={6}>
          <span>{value}</span>
          {!record.is_active && (
            <Tag color="default" bordered={false}>
              已停用
            </Tag>
          )}
          {record.code && <Tag color="blue">{record.code}</Tag>}
        </Space>
      ),
    },
    {
      title: '层级',
      dataIndex: 'level',
      key: 'level',
      width: 90,
      align: 'center',
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      key: 'sort_order',
      width: 90,
      align: 'center',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 110,
      render: (active: boolean, record: Department) => (
        <Switch
          size="small"
          checked={active}
          checkedChildren="启用"
          unCheckedChildren="停用"
          disabled={!canUpdate}
          onChange={(checked) => handleToggleActive(record, checked)}
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 210,
      render: (_: unknown, record: Department) => (
        <Space size={4}>
          {canCreate && record.is_active && record.level < MAX_LEVEL && (
            <Button type="link" size="small" onClick={() => openCreate(record.id)}>
              新增子部门
            </Button>
          )}
          {canUpdate && (
            <Button type="link" size="small" onClick={() => openEdit(record)}>
              编辑
            </Button>
          )}
          {canDelete && (
            <Popconfirm
              title="确认删除该部门？"
              description="存在子部门、任职记录或归属智能体时无法删除。"
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

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">部门管理</h2>
          <p className="page-header__desc">
            维护租户组织层级，最多 {MAX_LEVEL} 级；停用部门不可再挂接任职或智能体。
          </p>
        </div>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate(null)}>
            新建根部门
          </Button>
        )}
      </div>

      <Table<Department>
        rowKey="id"
        columns={columns}
        dataSource={tree}
        loading={loading}
        pagination={false}
        expandable={{
          expandedRowKeys,
          onExpandedRowsChange: (keys) => {
            const expanded = new Set(keys as string[])
            setCollapsedKeys(
              new Set(flatDepartments.filter((item) => !expanded.has(item.id)).map((item) => item.id)),
            )
          },
        }}
      />

      <Modal
        title={editing ? '编辑部门' : presetParentId ? '新增子部门' : '新建根部门'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={editing ? '保存' : '创建'}
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form<DepartmentFormValues> form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="parent_id"
            label="上级部门"
            extra="不选择则为根部门；最多 10 级，已停用部门不可选。"
          >
            <TreeSelect
              allowClear
              treeData={editableTreeData}
              placeholder="不选为根部门"
              treeDefaultExpandAll
            />
          </Form.Item>
          <Form.Item
            name="name"
            label="部门名称"
            rules={[
              { required: true, message: '请输入部门名称' },
              { max: 100, message: '部门名称最长 100 个字符' },
            ]}
          >
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item
            name="code"
            label="部门编码"
            extra="租户内唯一，仅小写字母、数字、下划线、短横线；留空表示不设编码。"
          >
            <Input maxLength={64} placeholder="例如 rd" />
          </Form.Item>
          <Form.Item name="sort_order" label="同级排序" initialValue={0}>
            <InputNumber min={0} max={999999} precision={0} style={{ width: '100%' }} />
          </Form.Item>
          {!editing && (
            <Form.Item name="is_active" label="启用" valuePropName="checked">
              <Switch checkedChildren="启用" unCheckedChildren="停用" />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  )
}
