import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  TreeSelect,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { departmentsApi } from '../../api/department'
import { mgmtUnitsApi } from '../../api/mgmtUnit'
import type { MgmtUnit } from '../../api/mgmtUnit'
import { usersApi } from '../../api/users'
import { useAuth } from '../../auth/AuthContext'

interface MgmtUnitFormValues {
  parent_id?: string | null
  name: string
  code?: string | null
  sort_order: number
  is_active?: boolean
}

interface BindingFormValues {
  bindings: Array<{ department_id: string; include_subtree: boolean }>
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
  const canCreate = hasPermission('button:mgmt-unit:create')
  const canUpdate = hasPermission('button:mgmt-unit:update')
  const canDelete = hasPermission('button:mgmt-unit:delete')

  const [tree, setTree] = useState<MgmtUnit[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<MgmtUnit | null>(null)
  const [form] = Form.useForm<MgmtUnitFormValues>()

  // 部门/人员关联弹窗
  const [bindingUnit, setBindingUnit] = useState<MgmtUnit | null>(null)
  const [bindingLoading, setBindingLoading] = useState(false)
  const [bindingSaving, setBindingSaving] = useState(false)
  const [deptOptions, setDeptOptions] = useState<{ label: string; value: string }[]>([])
  const [userOptions, setUserOptions] = useState<{ label: string; value: string }[]>([])
  const [deptBindings, setDeptBindings] = useState<BindingFormValues['bindings']>([])
  const [userIds, setUserIds] = useState<string[]>([])

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
      } else {
        await mgmtUnitsApi.create({
          parent_id: values.parent_id ?? null,
          name: values.name,
          code: values.code || null,
          sort_order: values.sort_order,
          attrs: {},
        })
        message.success('管理单元已创建')
      }
      setModalOpen(false)
      void load()
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

  const openBinding = async (unit: MgmtUnit) => {
    setBindingUnit(unit)
    setBindingLoading(true)
    try {
      const [depts, users, deptResp, userOptions] = await Promise.all([
        mgmtUnitsApi.listDepartments(unit.id),
        mgmtUnitsApi.listUsers(unit.id),
        departmentsApi.tree(),
        usersApi.options(),
      ])
      setDeptBindings(depts.map((d) => ({ department_id: d.department_id, include_subtree: d.include_subtree })))
      setUserIds(users.map((u) => u.user_id))
      setDeptOptions(
        deptResp.map((d) => ({
          label: `${'　'.repeat(d.level - 1)}${d.name}`,
          value: d.id,
        })),
      )
      setUserOptions(
        userOptions.map((u) => ({
          label: `${u.display_name || u.username}（${u.username}）`,
          value: u.id,
        })),
      )
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载关联失败')
      setBindingUnit(null)
    } finally {
      setBindingLoading(false)
    }
  }

  const saveBinding = async () => {
    if (!bindingUnit) return
    setBindingSaving(true)
    try {
      await Promise.all([
        mgmtUnitsApi.replaceDepartments(bindingUnit.id, deptBindings),
        mgmtUnitsApi.replaceUsers(bindingUnit.id, userIds),
      ])
      message.success('关联已保存')
      setBindingUnit(null)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存关联失败')
    } finally {
      setBindingSaving(false)
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
          {text}
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
      width: 320,
      render: (_, unit) => (
        <Space>
          {canCreate && unit.level < MAX_LEVEL && (
            <Button size="small" onClick={() => openCreate(unit.id)}>
              新增下级
            </Button>
          )}
          {canUpdate && (
            <>
              <Button size="small" onClick={() => openEdit(unit)}>
                编辑
              </Button>
              <Button size="small" onClick={() => void openBinding(unit)}>
                关联部门/人员
              </Button>
            </>
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
        destroyOnClose
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

      <Modal
        open={bindingUnit !== null}
        title={`关联部门/人员：${bindingUnit?.name ?? ''}`}
        onCancel={() => setBindingUnit(null)}
        onOk={() => void saveBinding()}
        confirmLoading={bindingSaving}
        width={640}
        loading={bindingLoading}
        destroyOnClose
      >
        <Tabs
          items={[
            {
              key: 'departments',
              label: '关联部门',
              children: (
                <Select
                  mode="multiple"
                  style={{ width: '100%' }}
                  placeholder="选择部门"
                  value={deptBindings.map((b) => b.department_id)}
                  options={deptOptions}
                  onChange={(values: string[]) => {
                    const next = new Map(deptBindings.map((b) => [b.department_id, b]))
                    for (const v of values) {
                      if (!next.has(v)) next.set(v, { department_id: v, include_subtree: false })
                    }
                    setDeptBindings(Array.from(next.values()).filter((b) => values.includes(b.department_id)))
                  }}
                  optionRender={(option) => {
                    const value = String(option.value)
                    const binding = deptBindings.find((b) => b.department_id === value)
                    return (
                      <Space>
                        <span>{option.label}</span>
                        <Checkbox
                          checked={binding?.include_subtree ?? false}
                          onChange={(e) => {
                            setDeptBindings((prev) =>
                              prev.map((b) =>
                                b.department_id === value
                                  ? { ...b, include_subtree: e.target.checked }
                                  : b,
                              ),
                            )
                          }}
                        >
                          含下级
                        </Checkbox>
                      </Space>
                    )
                  }}
                />
              ),
            },
            {
              key: 'users',
              label: '关联人员',
              children: (
                <Select
                  mode="multiple"
                  style={{ width: '100%' }}
                  placeholder="选择人员"
                  value={userIds}
                  options={userOptions}
                  onChange={(values: string[]) => setUserIds(values)}
                />
              ),
            },
          ]}
        />
      </Modal>
    </>
  )
}
