import { ArrowLeftOutlined, PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { departmentsApi } from '../../api/department'
import { mgmtUnitsApi } from '../../api/mgmtUnit'
import type { MgmtUnit, MgmtUnitDepartment, MgmtUnitUser } from '../../api/mgmtUnit'
import type { Department, UserOption } from '../../api/types'
import { usersApi } from '../../api/users'
import { useAuth } from '../../auth/AuthContext'

interface DeptSelection {
  department_id: string
  include_subtree: boolean
}

function findUnitById(units: MgmtUnit[], id: string): MgmtUnit | null {
  for (const unit of units) {
    if (unit.id === id) return unit
    if (unit.children) {
      const hit = findUnitById(unit.children, id)
      if (hit) return hit
    }
  }
  return null
}

function flattenDepartments(departments: Department[]): Department[] {
  return departments.flatMap((dept) => [
    dept,
    ...flattenDepartments(dept.children ?? []),
  ])
}

export default function MgmtUnitDetailPage() {
  const { id } = useParams()
  const unitId = id ?? ''
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canUpdate = hasPermission('button:mgmt-unit:update')

  const [unit, setUnit] = useState<MgmtUnit | null>(null)
  const [unitLoading, setUnitLoading] = useState(false)

  const [deptBindings, setDeptBindings] = useState<MgmtUnitDepartment[]>([])
  const [deptLoading, setDeptLoading] = useState(false)
  const [deptKeyword, setDeptKeyword] = useState('')
  const [deptModalOpen, setDeptModalOpen] = useState(false)
  const [deptModalSaving, setDeptModalSaving] = useState(false)
  const [deptSelections, setDeptSelections] = useState<DeptSelection[]>([])

  const [userBindings, setUserBindings] = useState<MgmtUnitUser[]>([])
  const [userLoading, setUserLoading] = useState(false)
  const [userKeyword, setUserKeyword] = useState('')
  const [userModalOpen, setUserModalOpen] = useState(false)
  const [userModalSaving, setUserModalSaving] = useState(false)
  const [userSelections, setUserSelections] = useState<string[]>([])

  const [deptFlatList, setDeptFlatList] = useState<Department[]>([])
  const [userOptionList, setUserOptionList] = useState<UserOption[]>([])

  const loadUnit = useCallback(async () => {
    if (!unitId) return
    setUnitLoading(true)
    try {
      const tree = await mgmtUnitsApi.tree()
      const found = findUnitById(tree, unitId)
      if (!found) {
        message.error('管理单元不存在或已被删除')
        navigate('/mgmt-units', { replace: true })
        return
      }
      setUnit(found)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载管理单元失败')
    } finally {
      setUnitLoading(false)
    }
  }, [unitId, message, navigate])

  const loadBindings = useCallback(async () => {
    if (!unitId) return
    setDeptLoading(true)
    setUserLoading(true)
    try {
      const [depts, users, deptTree, userOptions] = await Promise.all([
        mgmtUnitsApi.listDepartments(unitId),
        mgmtUnitsApi.listUsers(unitId),
        departmentsApi.tree(),
        usersApi.options(),
      ])
      setDeptBindings(depts)
      setUserBindings(users)
      setDeptFlatList(flattenDepartments(deptTree))
      setUserOptionList(userOptions)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载关联数据失败')
    } finally {
      setDeptLoading(false)
      setUserLoading(false)
    }
  }, [unitId, message])

  useEffect(() => {
    void loadUnit()
  }, [loadUnit])

  useEffect(() => {
    void loadBindings()
  }, [loadBindings])

  const deptMap = useMemo(() => new Map(deptFlatList.map((d) => [d.id, d])), [deptFlatList])
  const userMap = useMemo(() => new Map(userOptionList.map((u) => [u.id, u])), [userOptionList])

  const filteredDeptBindings = useMemo(() => {
    const kw = deptKeyword.trim().toLowerCase()
    if (!kw) return deptBindings
    return deptBindings.filter((binding) => {
      const dept = deptMap.get(binding.department_id)
      return dept?.name.toLowerCase().includes(kw) ?? false
    })
  }, [deptBindings, deptKeyword, deptMap])

  const filteredUserBindings = useMemo(() => {
    const kw = userKeyword.trim().toLowerCase()
    if (!kw) return userBindings
    return userBindings.filter((binding) => {
      const user = userMap.get(binding.user_id)
      if (!user) return false
      return (
        (user.display_name || '').toLowerCase().includes(kw) ||
        user.username.toLowerCase().includes(kw)
      )
    })
  }, [userBindings, userKeyword, userMap])

  const applyDeptBindings = useCallback(
    (next: DeptSelection[]) => {
      setDeptBindings(
        next.map((item) => ({
          unit_id: unitId,
          department_id: item.department_id,
          include_subtree: item.include_subtree,
        })),
      )
    },
    [unitId],
  )

  const applyUserBindings = useCallback(
    (next: string[]) => {
      setUserBindings(next.map((user_id) => ({ unit_id: unitId, user_id })))
    },
    [unitId],
  )

  const handleRemoveDept = async (departmentId: string) => {
    const next = deptBindings
      .filter((b) => b.department_id !== departmentId)
      .map((b) => ({ department_id: b.department_id, include_subtree: b.include_subtree }))
    try {
      await mgmtUnitsApi.replaceDepartments(unitId, next)
      applyDeptBindings(next)
      message.success('已移除')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '移除部门失败')
    }
  }

  const handleRemoveUser = async (userId: string) => {
    const next = userBindings.filter((b) => b.user_id !== userId).map((b) => b.user_id)
    try {
      await mgmtUnitsApi.replaceUsers(unitId, next)
      applyUserBindings(next)
      message.success('已移除')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '移除人员失败')
    }
  }

  const openDeptModal = () => {
    setDeptSelections(
      deptBindings.map((b) => ({
        department_id: b.department_id,
        include_subtree: b.include_subtree,
      })),
    )
    setDeptModalOpen(true)
  }

  const saveDeptModal = async () => {
    setDeptModalSaving(true)
    try {
      await mgmtUnitsApi.replaceDepartments(unitId, deptSelections)
      applyDeptBindings(deptSelections)
      setDeptModalOpen(false)
      message.success('关联部门已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存关联部门失败')
    } finally {
      setDeptModalSaving(false)
    }
  }

  const openUserModal = () => {
    setUserSelections(userBindings.map((b) => b.user_id))
    setUserModalOpen(true)
  }

  const saveUserModal = async () => {
    setUserModalSaving(true)
    try {
      await mgmtUnitsApi.replaceUsers(unitId, userSelections)
      applyUserBindings(userSelections)
      setUserModalOpen(false)
      message.success('关联人员已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存关联人员失败')
    } finally {
      setUserModalSaving(false)
    }
  }

  const deptColumns: ColumnsType<MgmtUnitDepartment> = [
    {
      title: '部门名称',
      key: 'name',
      render: (_: unknown, record) => {
        const dept = deptMap.get(record.department_id)
        if (!dept) return <span style={{ color: '#999' }}>{record.department_id}</span>
        return (
          <span>
            {'　'.repeat(dept.level - 1)}
            {dept.name}
          </span>
        )
      },
    },
    {
      title: '部门编码',
      key: 'code',
      width: 160,
      render: (_: unknown, record) => deptMap.get(record.department_id)?.code || '-',
    },
    {
      title: '范围',
      dataIndex: 'include_subtree',
      key: 'include_subtree',
      width: 100,
      render: (include: boolean) =>
        include ? <Tag color="blue">含下级</Tag> : <Tag>仅本级</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, record) =>
        canUpdate ? (
          <Popconfirm
            title="确认移除该部门？"
            onConfirm={() => void handleRemoveDept(record.department_id)}
          >
            <Button size="small" danger>
              移除
            </Button>
          </Popconfirm>
        ) : null,
    },
  ]

  const userColumns: ColumnsType<MgmtUnitUser> = [
    {
      title: '姓名',
      key: 'display_name',
      render: (_: unknown, record) => userMap.get(record.user_id)?.display_name || '-',
    },
    {
      title: '账号',
      key: 'username',
      width: 180,
      render: (_: unknown, record) => userMap.get(record.user_id)?.username || '-',
    },
    {
      title: '状态',
      key: 'is_active',
      width: 100,
      render: (_: unknown, record) => {
        const user = userMap.get(record.user_id)
        if (!user) return '-'
        return user.is_active ? <Tag color="success">启用</Tag> : <Tag color="default">停用</Tag>
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, record) =>
        canUpdate ? (
          <Popconfirm
            title="确认移除该人员？"
            onConfirm={() => void handleRemoveUser(record.user_id)}
          >
            <Button size="small" danger>
              移除
            </Button>
          </Popconfirm>
        ) : null,
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <Space size={8}>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/mgmt-units')}
            />
            <h2 className="page-header__title">{unit?.name ?? '管理单元详情'}</h2>
          </Space>
          <p className="page-header__desc">维护该管理单元覆盖的部门范围与人员列表。</p>
        </div>
      </div>

      <Card size="small" loading={unitLoading} style={{ marginBottom: 16 }}>
        <Descriptions column={3} size="small">
          <Descriptions.Item label="编码">{unit?.code || '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            {unit ? (
              unit.is_active ? (
                <Tag color="success">启用</Tag>
              ) : (
                <Tag color="danger">停用</Tag>
              )
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="排序">{unit?.sort_order ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {unit ? dayjs(unit.created_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {unit ? dayjs(unit.updated_at).format('YYYY-MM-DD HH:mm') : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small">
        <Tabs
          items={[
            {
              key: 'departments',
              label: (
                <span>
                  关联部门
                  <Tag bordered={false} style={{ marginLeft: 6 }}>
                    {deptBindings.length}
                  </Tag>
                </span>
              ),
              children: (
                <>
                  <div className="page-toolbar">
                    <Input.Search
                      allowClear
                      placeholder="搜索部门名称"
                      style={{ width: 260 }}
                      onChange={(e) => setDeptKeyword(e.target.value)}
                    />
                    {canUpdate && (
                      <Button type="primary" icon={<PlusOutlined />} onClick={openDeptModal}>
                        添加部门
                      </Button>
                    )}
                  </div>
                  <Table<MgmtUnitDepartment>
                    rowKey="department_id"
                    loading={deptLoading}
                    columns={deptColumns}
                    dataSource={filteredDeptBindings}
                    pagination={false}
                  />
                </>
              ),
            },
            {
              key: 'users',
              label: (
                <span>
                  关联人员
                  <Tag bordered={false} style={{ marginLeft: 6 }}>
                    {userBindings.length}
                  </Tag>
                </span>
              ),
              children: (
                <>
                  <div className="page-toolbar">
                    <Input.Search
                      allowClear
                      placeholder="搜索姓名或账号"
                      style={{ width: 260 }}
                      onChange={(e) => setUserKeyword(e.target.value)}
                    />
                    {canUpdate && (
                      <Button type="primary" icon={<PlusOutlined />} onClick={openUserModal}>
                        添加人员
                      </Button>
                    )}
                  </div>
                  <Table<MgmtUnitUser>
                    rowKey="user_id"
                    loading={userLoading}
                    columns={userColumns}
                    dataSource={filteredUserBindings}
                    pagination={false}
                  />
                </>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        open={deptModalOpen}
        title="关联部门"
        onCancel={() => setDeptModalOpen(false)}
        onOk={() => void saveDeptModal()}
        confirmLoading={deptModalSaving}
        width={640}
        destroyOnHidden
      >
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          placeholder="选择部门"
          value={deptSelections.map((s) => s.department_id)}
          options={deptFlatList.map((d) => ({
            label: `${'　'.repeat(d.level - 1)}${d.name}`,
            value: d.id,
          }))}
          onChange={(values: string[]) => {
            const next = new Map(deptSelections.map((s) => [s.department_id, s]))
            for (const v of values) {
              if (!next.has(v)) next.set(v, { department_id: v, include_subtree: false })
            }
            setDeptSelections(
              Array.from(next.values()).filter((s) => values.includes(s.department_id)),
            )
          }}
          optionRender={(option) => {
            const value = String(option.value)
            const selection = deptSelections.find((s) => s.department_id === value)
            return (
              <Space>
                <span>{option.label}</span>
                <Checkbox
                  checked={selection?.include_subtree ?? false}
                  onChange={(e) => {
                    setDeptSelections((prev) =>
                      prev.map((s) =>
                        s.department_id === value
                          ? { ...s, include_subtree: e.target.checked }
                          : s,
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
      </Modal>

      <Modal
        open={userModalOpen}
        title="关联人员"
        onCancel={() => setUserModalOpen(false)}
        onOk={() => void saveUserModal()}
        confirmLoading={userModalSaving}
        width={640}
        destroyOnHidden
      >
        <Select
          mode="multiple"
          showSearch
          style={{ width: '100%' }}
          placeholder="选择人员"
          value={userSelections}
          options={userOptionList.map((u) => ({
            label: `${u.display_name || u.username}（${u.username}）`,
            value: u.id,
          }))}
          onChange={(values: string[]) => setUserSelections(values)}
          filterOption={(input, option) => {
            const label = String(option?.label ?? '')
            return label.toLowerCase().includes(input.toLowerCase())
          }}
        />
      </Modal>
    </div>
  )
}
