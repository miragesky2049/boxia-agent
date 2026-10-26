import { PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  DatePicker,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  TreeSelect,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { departmentsApi } from '../../api/department'
import { employmentsApi } from '../../api/employment'
import type { Department, Employment } from '../../api/types'
import { usersApi } from '../../api/users'
import { useAuth } from '../../auth/AuthContext'
import { buildDepartmentTreeData } from '../../utils/departmentTree'

interface CreateFormValues {
  user_id: string
  department_id: string
  position?: string
  started_at?: dayjs.Dayjs
}

interface EditFormValues {
  position?: string
  started_at?: dayjs.Dayjs
}

interface TransferFormValues {
  department_id: string
  position?: string
  started_at?: dayjs.Dayjs
}

type StatusFilter = 'all' | 'current' | 'history'

export default function EmploymentsPage() {
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = hasPermission('button:employment:create')
  const canUpdate = hasPermission('button:employment:update')
  const canDelete = hasPermission('button:employment:delete')
  const showActions = canUpdate || canDelete

  const [items, setItems] = useState<Employment[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [filterDepartmentId, setFilterDepartmentId] = useState<string | undefined>(undefined)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [departmentTree, setDepartmentTree] = useState<Department[]>([])
  const [userOptions, setUserOptions] = useState<{ label: string; value: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Employment | null>(null)
  const [transferring, setTransferring] = useState<Employment | null>(null)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editForm] = Form.useForm<EditFormValues>()
  const [transferForm] = Form.useForm<TransferFormValues>()

  const departmentTreeData = useMemo(
    () => buildDepartmentTreeData(departmentTree),
    [departmentTree],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await employmentsApi.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        department_id: filterDepartmentId,
        is_current:
          statusFilter === 'all' ? undefined : statusFilter === 'current',
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '任职记录加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, filterDepartmentId, statusFilter, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    departmentsApi
      .tree()
      .then(setDepartmentTree)
      .catch(() => setDepartmentTree([]))
    usersApi
      .list({ page: 1, page_size: 100 })
      .then((result) =>
        setUserOptions(
          result.items.map((user) => ({
            label: `${user.display_name || user.username}（${user.username}）`,
            value: user.id,
          })),
        ),
      )
      .catch(() => setUserOptions([]))
  }, [])

  const openCreate = () => {
    createForm.resetFields()
    setCreateOpen(true)
  }

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    setSaving(true)
    try {
      await employmentsApi.create({
        user_id: values.user_id,
        department_id: values.department_id,
        position: values.position?.trim() ?? '',
        started_at: values.started_at?.format('YYYY-MM-DD'),
      })
      message.success('任职已创建')
      setCreateOpen(false)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const openEdit = (record: Employment) => {
    setEditing(record)
    editForm.setFieldsValue({
      position: record.position,
      started_at: dayjs(record.started_at),
    })
  }

  const handleEdit = async () => {
    if (!editing) return
    const values = await editForm.validateFields()
    setSaving(true)
    try {
      await employmentsApi.update(editing.id, {
        position: values.position?.trim(),
        started_at: values.started_at?.format('YYYY-MM-DD'),
      })
      message.success('已保存')
      setEditing(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const openTransfer = (record: Employment) => {
    setTransferring(record)
    transferForm.setFieldsValue({
      department_id: record.department_id,
      position: record.position,
      started_at: dayjs(),
    })
  }

  const handleTransfer = async () => {
    if (!transferring) return
    const values = await transferForm.validateFields()
    setSaving(true)
    try {
      await employmentsApi.transfer(transferring.id, {
        department_id: values.department_id,
        position: values.position?.trim(),
        started_at: values.started_at?.format('YYYY-MM-DD'),
      })
      message.success('调岗成功，原任职已归档')
      setTransferring(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '调岗失败')
    } finally {
      setSaving(false)
    }
  }

  const handleArchive = async (record: Employment) => {
    try {
      await employmentsApi.archive(record.id)
      message.success('任职已结束')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handleDelete = async (record: Employment) => {
    try {
      await employmentsApi.remove(record.id)
      message.success('任职记录已删除')
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const columns: ColumnsType<Employment> = [
    {
      title: '用户',
      key: 'user',
      width: 200,
      render: (_: unknown, record: Employment) => (
        <div>
          <div className="resource-name">{record.user_display_name || record.user_name}</div>
          <div className="resource-desc">{record.user_name}</div>
        </div>
      ),
    },
    {
      title: '部门',
      dataIndex: 'department_name',
      key: 'department_name',
      width: 160,
    },
    {
      title: '岗位',
      dataIndex: 'position',
      key: 'position',
      width: 140,
      render: (value: string) => value || '-',
    },
    {
      title: '状态',
      dataIndex: 'is_current',
      key: 'is_current',
      width: 100,
      render: (current: boolean) =>
        current ? (
          <Tag color="green" bordered={false}>
            当前
          </Tag>
        ) : (
          <Tag color="default" bordered={false}>
            历史
          </Tag>
        ),
    },
    {
      title: '任职区间',
      key: 'period',
      width: 200,
      render: (_: unknown, record: Employment) =>
        `${record.started_at} ~ ${record.ended_at ?? '至今'}`,
    },
    ...(showActions
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 210,
            render: (_: unknown, record: Employment) => (
              <Space size={4}>
                {canUpdate && record.is_current && (
                  <Button type="link" size="small" onClick={() => openTransfer(record)}>
                    调岗
                  </Button>
                )}
                {canUpdate && (
                  <Button type="link" size="small" onClick={() => openEdit(record)}>
                    编辑
                  </Button>
                )}
                {canUpdate && record.is_current && (
                  <Popconfirm
                    title="确认结束该任职？"
                    description="结束日期默认为今天，结束后用户变为无当前部门。"
                    okText="结束"
                    cancelText="取消"
                    onConfirm={() => handleArchive(record)}
                  >
                    <Button type="link" size="small">
                      结束任职
                    </Button>
                  </Popconfirm>
                )}
                {canDelete && (
                  <Popconfirm
                    title="确认删除该任职记录？"
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

  const resetPageAndApply = (apply: () => void) => {
    setPage(1)
    apply()
  }

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">任职管理</h2>
          <p className="page-header__desc">
            每个用户同时仅保留一条当前任职；调岗自动归档原记录并保留完整历史。
          </p>
        </div>
        {canCreate && (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增任职
          </Button>
        )}
      </div>

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索用户名、显示名或岗位"
          style={{ width: 280 }}
          onSearch={(value) => resetPageAndApply(() => setKeyword(value.trim()))}
        />
        <TreeSelect
          allowClear
          style={{ width: 240 }}
          placeholder="按部门筛选（含下级）"
          treeData={departmentTreeData}
          onChange={(value: string | undefined) =>
            resetPageAndApply(() => setFilterDepartmentId(value))
          }
        />
        <Select<StatusFilter>
          style={{ width: 140 }}
          value={statusFilter}
          options={[
            { label: '全部状态', value: 'all' },
            { label: '当前任职', value: 'current' },
            { label: '历史任职', value: 'history' },
          ]}
          onChange={(value) => resetPageAndApply(() => setStatusFilter(value))}
        />
      </div>

      <Table<Employment>
        rowKey="id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (count) => `共 ${count} 条任职记录`,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
      />

      <Modal
        title="新增任职"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={saving}
        okText="创建"
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form<CreateFormValues> form={createForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="user_id"
            label="用户"
            rules={[{ required: true, message: '请选择用户' }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={userOptions}
              placeholder="选择用户"
            />
          </Form.Item>
          <Form.Item
            name="department_id"
            label="所属部门"
            rules={[{ required: true, message: '请选择部门' }]}
          >
            <TreeSelect
              treeData={departmentTreeData}
              placeholder="选择部门"
              treeDefaultExpandAll
            />
          </Form.Item>
          <Form.Item name="position" label="岗位">
            <Input maxLength={100} placeholder="例如：客服专员" />
          </Form.Item>
          <Form.Item name="started_at" label="生效日期" extra="不选默认为今天。">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editing ? `编辑任职：${editing.user_display_name || editing.user_name}` : '编辑任职'}
        open={Boolean(editing)}
        onOk={handleEdit}
        onCancel={() => setEditing(null)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form<EditFormValues> form={editForm} layout="vertical" requiredMark={false}>
          <Form.Item name="position" label="岗位">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="started_at" label="生效日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={
          transferring
            ? `调岗：${transferring.user_display_name || transferring.user_name}`
            : '调岗'
        }
        open={Boolean(transferring)}
        onOk={handleTransfer}
        onCancel={() => setTransferring(null)}
        confirmLoading={saving}
        okText="确认调岗"
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form<TransferFormValues> form={transferForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="department_id"
            label="调入部门"
            rules={[{ required: true, message: '请选择调入部门' }]}
          >
            <TreeSelect
              treeData={departmentTreeData}
              treeDefaultExpandAll
              placeholder="选择新部门"
            />
          </Form.Item>
          <Form.Item name="position" label="新岗位" extra="留空沿用原岗位。">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="started_at" label="生效日期" extra="不选默认为今天；原任职结束日期为生效日期前一天。">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
