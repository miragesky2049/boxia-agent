import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Checkbox,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAgentVisibility, saveAgentVisibility } from '../../api/agents'
import { departmentsApi } from '../../api/department'
import type {
  AgentVisibilityDepartmentItem,
  AgentVisibilityMode,
  Department,
  UserOption,
} from '../../api/types'
import { usersApi } from '../../api/users'

function flattenDepartments(departments: Department[]): Department[] {
  return departments.flatMap((dept) => [
    dept,
    ...flattenDepartments(dept.children ?? []),
  ])
}

export default function AgentVisibilityTab({ agentId }: { agentId: string }) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const [mode, setMode] = useState<AgentVisibilityMode>('all')
  const [departments, setDepartments] = useState<AgentVisibilityDepartmentItem[]>([])
  const [userIds, setUserIds] = useState<string[]>([])

  const [deptFlatList, setDeptFlatList] = useState<Department[]>([])
  const [userOptionList, setUserOptionList] = useState<UserOption[]>([])

  const [deptModalOpen, setDeptModalOpen] = useState(false)
  const [deptSelections, setDeptSelections] = useState<AgentVisibilityDepartmentItem[]>([])
  const [userModalOpen, setUserModalOpen] = useState(false)
  const [userSelections, setUserSelections] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [visibility, deptTree, userOptions] = await Promise.all([
        getAgentVisibility(agentId),
        departmentsApi.tree().catch(() => [] as Department[]),
        usersApi.options().catch(() => [] as UserOption[]),
      ])
      setMode(visibility.mode)
      setDepartments(visibility.departments)
      setUserIds(visibility.user_ids)
      setDeptFlatList(flattenDepartments(deptTree))
      setUserOptionList(userOptions)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载可见范围失败')
    } finally {
      setLoading(false)
    }
  }, [agentId, message])

  useEffect(() => {
    void load()
  }, [load])

  const deptMap = useMemo(() => new Map(deptFlatList.map((d) => [d.id, d])), [deptFlatList])
  const userMap = useMemo(() => new Map(userOptionList.map((u) => [u.id, u])), [userOptionList])

  const handleSave = async () => {
    setSaving(true)
    try {
      const result = await saveAgentVisibility(agentId, {
        mode,
        departments: mode === 'custom' ? departments : [],
        user_ids: mode === 'custom' ? userIds : [],
      })
      setMode(result.mode)
      setDepartments(result.departments)
      setUserIds(result.user_ids)
      message.success('可见范围已保存')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存可见范围失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleDeptSubtree = (departmentId: string, includeSubtree: boolean) => {
    setDepartments((prev) =>
      prev.map((item) =>
        item.department_id === departmentId ? { ...item, include_subtree: includeSubtree } : item,
      ),
    )
  }

  const removeDept = (departmentId: string) => {
    setDepartments((prev) => prev.filter((item) => item.department_id !== departmentId))
  }

  const removeUser = (userId: string) => {
    setUserIds((prev) => prev.filter((id) => id !== userId))
  }

  const openDeptModal = () => {
    setDeptSelections(departments)
    setDeptModalOpen(true)
  }

  const confirmDeptModal = () => {
    setDepartments(deptSelections)
    setDeptModalOpen(false)
  }

  const openUserModal = () => {
    setUserSelections(userIds)
    setUserModalOpen(true)
  }

  const confirmUserModal = () => {
    setUserIds(userSelections)
    setUserModalOpen(false)
  }

  const deptColumns: ColumnsType<AgentVisibilityDepartmentItem> = [
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
      title: '含下级',
      dataIndex: 'include_subtree',
      key: 'include_subtree',
      width: 120,
      render: (value: boolean, record) => (
        <Switch
          checked={value}
          checkedChildren="含子树"
          unCheckedChildren="仅本级"
          onChange={(checked) => toggleDeptSubtree(record.department_id, checked)}
        />
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      render: (_: unknown, record) => (
        <Popconfirm
          title="确认移除该部门？"
          onConfirm={() => removeDept(record.department_id)}
        >
          <Button size="small" danger>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  const userColumns: ColumnsType<{ user_id: string }> = [
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
      render: (_: unknown, record) => (
        <Popconfirm title="确认移除该人员？" onConfirm={() => removeUser(record.user_id)}>
          <Button size="small" danger>
            移除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }} loading={loading}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value as AgentVisibilityMode)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="all">全员可见</Radio.Button>
            <Radio.Button value="custom">自定义范围</Radio.Button>
          </Radio.Group>
          <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
            {mode === 'all'
              ? '租户内所有 user 端普通用户均可看到该智能体。'
              : '仅当用户属于下列部门（含子部门）或被直接指定时，才能在 user 端看到该智能体。'}
          </div>
        </Space>
      </Card>

      {mode === 'custom' && (
        <>
          <Card
            size="small"
            title={
              <span>
                可见部门
                <Tag bordered={false} style={{ marginLeft: 6 }}>
                  {departments.length}
                </Tag>
              </span>
            }
            style={{ marginBottom: 16 }}
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={openDeptModal}>
                添加部门
              </Button>
            }
          >
            <Table<AgentVisibilityDepartmentItem>
              rowKey="department_id"
              columns={deptColumns}
              dataSource={departments}
              loading={loading}
              pagination={false}
            />
          </Card>

          <Card
            size="small"
            title={
              <span>
                可见人员
                <Tag bordered={false} style={{ marginLeft: 6 }}>
                  {userIds.length}
                </Tag>
              </span>
            }
            style={{ marginBottom: 16 }}
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={openUserModal}>
                添加人员
              </Button>
            }
          >
            <Table<{ user_id: string }>
              rowKey="user_id"
              columns={userColumns}
              dataSource={userIds.map((user_id) => ({ user_id }))}
              loading={loading}
              pagination={false}
            />
          </Card>
        </>
      )}

      <Space>
        <Button type="primary" loading={saving} onClick={() => void handleSave()}>
          保存可见范围
        </Button>
      </Space>

      <Modal
        open={deptModalOpen}
        title="选择可见部门"
        onCancel={() => setDeptModalOpen(false)}
        onOk={confirmDeptModal}
        width={640}
        destroyOnClose
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
              if (!next.has(v)) next.set(v, { department_id: v, include_subtree: true })
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
                  checked={selection?.include_subtree ?? true}
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
        title="选择可见人员"
        onCancel={() => setUserModalOpen(false)}
        onOk={confirmUserModal}
        width={640}
        destroyOnClose
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
