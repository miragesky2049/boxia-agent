import { SafetyCertificateOutlined } from '@ant-design/icons'
import { Alert, App, Button, Form, Input, Modal, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { grantsApi, rolesApi } from '../../api/access'
import { mgmtUnitsApi } from '../../api/mgmtUnit'
import type { MgmtUnit, Role, User } from '../../api/types'
import { usersApi } from '../../api/users'
import { useAuth } from '../../auth/AuthContext'

interface AssignFormValues {
  role_ids: string[]
  mgmt_unit_ids: string[]
}

const MAX_BATCH_SELECTION = 100

export default function UserGrantsPage() {
  const { hasPermission } = useAuth()
  const canManage = hasPermission('button:grant:manage')
  const { message } = App.useApp()
  const [items, setItems] = useState<User[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [roles, setRoles] = useState<Role[]>([])
  const [units, setUnits] = useState<MgmtUnit[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([])
  const [targets, setTargets] = useState<User[]>([])
  const [form] = Form.useForm<AssignFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await usersApi.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载用户失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    rolesApi
      .list({ include_inactive: true })
      .then(setRoles)
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载角色失败'),
      )
  }, [message])

  useEffect(() => {
    mgmtUnitsApi
      .active()
      .then(setUnits)
      .catch((error: unknown) =>
        message.error(error instanceof Error ? error.message : '加载管理单元失败'),
      )
  }, [message])

  const roleOptions = roles
    .filter((role) => role.is_active)
    .map((role) => ({ label: role.name, value: role.id }))

  const unitOptions = units.map((unit) => ({ label: unit.name, value: unit.id }))

  const roleNames = (roleIds: string[]) =>
    roleIds.map((roleId) => {
      const role = roles.find((item) => item.id === roleId)
      if (!role) return `角色 #${roleId}`
      return role.is_active ? role.name : `${role.name}（停用）`
    })

  const openAssign = (records: User[]) => {
    if (!records.length) {
      message.error('请先选择用户')
      return
    }
    setTargets(records)
    form.resetFields()
    form.setFieldsValue({ role_ids: [], mgmt_unit_ids: [] })
  }

  const handleAssign = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const result = await grantsApi.assignUserRoles({
        user_ids: targets.map((user) => user.id),
        role_ids: values.role_ids,
        mgmt_unit_ids: values.mgmt_unit_ids,
      })
      message.success(`已为 ${targets.length} 个用户追加授权，新增 ${result.updated} 条角色关联`)
      setTargets([])
      setSelectedRowKeys([])
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '分配授权失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<User> = [
    {
      title: '账号',
      key: 'account',
      width: 240,
      render: (_: unknown, record: User) => (
        <div>
          <div className="resource-name">{record.display_name || record.username}</div>
          <div className="resource-desc">{record.username}</div>
        </div>
      ),
    },
    {
      title: '当前角色',
      key: 'roles',
      render: (_: unknown, record: User) => (
        <Space size={4} wrap>
          {roleNames(record.role_ids).map((name, index) => (
            <Tag key={`${record.id}-${index}`} color="green">
              {name}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 90,
      render: (enabled: boolean) =>
        enabled ? <Tag color="success">启用</Tag> : <Tag>禁用</Tag>,
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      key: 'last_login_at',
      width: 170,
      render: (value: string | null) =>
        value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '从未登录',
    },
    ...(canManage
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 100,
            render: (_: unknown, record: User) => (
              <Button type="link" size="small" onClick={() => openAssign([record])}>
                分配授权
              </Button>
            ),
          },
        ]
      : []),
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">用户授权</h2>
          <p className="page-header__desc">
            为用户分配角色（功能权限）+ 管理单元（数据权限）；角色决定菜单与按钮，管理单元决定可见的智能体范围。
          </p>
        </div>
        {canManage && (
          <Button
            type="primary"
            icon={<SafetyCertificateOutlined />}
            disabled={selectedRowKeys.length === 0}
            onClick={() => openAssign(items.filter((item) => selectedRowKeys.includes(item.id)))}
          >
            批量分配授权
          </Button>
        )}
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        message="批量授权为追加操作，不会移除用户已有角色与管理单元。"
      />

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索账号或显示名"
          style={{ width: 280 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
            setSelectedRowKeys([])
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {total} 个用户
        </Tag>
        {selectedRowKeys.length > 0 && (
          <Tag color="orange" bordered={false}>
            已选 {selectedRowKeys.length} 个
          </Tag>
        )}
      </div>

      <Table<User>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => {
            if (keys.length > MAX_BATCH_SELECTION) {
              message.warning(`单次最多选择 ${MAX_BATCH_SELECTION} 个用户`)
              return
            }
            setSelectedRowKeys(keys.map(String))
          },
        }}
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
            setSelectedRowKeys([])
          },
        }}
      />

      <Modal
        title={`分配授权${targets.length === 1 ? `：${targets[0]?.username ?? ''}` : ''}`}
        open={targets.length > 0}
        onOk={() => void handleAssign()}
        onCancel={() => setTargets([])}
        confirmLoading={saving}
        okText="追加授权"
        cancelText="取消"
        width={560}
        forceRender
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={`将为 ${targets.length} 个用户同时追加所选角色与管理单元；已拥有的关联保持不变。`}
        />
        <Form<AssignFormValues> form={form} layout="vertical" requiredMark={false}>
          <Form.Item
            name="role_ids"
            label="追加角色（功能权限）"
            rules={[{ required: true, message: '请至少选择一个角色' }]}
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="选择要追加的角色"
              options={roleOptions}
            />
          </Form.Item>
          <Form.Item
            name="mgmt_unit_ids"
            label="追加管理单元（数据权限）"
            rules={[{ required: true, message: '请至少选择一个管理单元' }]}
            extra="用户将可见其被授权管理单元关联部门/人员创建的智能体；未授权任何单元时仅可见本人创建。"
          >
            <Select
              mode="multiple"
              allowClear
              placeholder="选择要追加的管理单元"
              options={unitOptions}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
