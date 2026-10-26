import { IdcardOutlined, PlusOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  TreeSelect,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { departmentsApi } from '../../api/department'
import { employmentsApi } from '../../api/employment'
import { hrDictionariesApi, type HrDictionaryCategory } from '../../api/hrDictionary'
import type {
  Department,
  Employment,
  HrDictionary,
  HrFieldsPayload,
} from '../../api/types'
import { usersApi } from '../../api/users'
import { useAuth } from '../../auth/AuthContext'
import { buildDepartmentTreeData } from '../../utils/departmentTree'
import HrDictionariesDrawer from './HrDictionariesDrawer'

const EMPLOYMENT_NATURE_OPTIONS = [
  { label: '正式', value: 'regular' },
  { label: '派遣', value: 'dispatch' },
  { label: '外包', value: 'outsourced' },
  { label: '实习', value: 'intern' },
]

const CHANGE_TYPE_OPTIONS = [
  { label: '入职', value: 'hire' },
  { label: '调岗', value: 'transfer' },
  { label: '晋升', value: 'promotion' },
  { label: '降职', value: 'demotion' },
  { label: '组织调整', value: 'reorganization' },
]

const TERMINATION_TYPE_OPTIONS = [
  { label: '主动辞职', value: 'resignation' },
  { label: '公司辞退', value: 'dismissal' },
  { label: '裁员', value: 'layoff' },
  { label: '退休', value: 'retirement' },
]

interface HrFormValues {
  employment_type_id?: string
  job_level_id?: string
  job_family_id?: string
  manager_id?: string
  work_location?: string
  cost_center?: string
  contract_no?: string
  weekly_hours?: number
  employment_nature?: string
  probation_started_at?: Dayjs
  probation_ended_at?: Dayjs
  regularized_at?: Dayjs
  change_reason?: string
  remark?: string
}

interface CreateFormValues extends HrFormValues {
  user_id: string
  department_id: string
  position?: string
  started_at?: Dayjs
}

interface EditFormValues extends HrFormValues {
  position?: string
  started_at?: Dayjs
}

interface TransferFormValues extends HrFormValues {
  department_id: string
  position?: string
  started_at?: Dayjs
  change_type: string
}

interface ArchiveFormValues {
  ended_at?: Dayjs
  termination_type?: string
  change_reason?: string
}

type StatusFilter = 'all' | 'current' | 'history'

function toDate(value?: Dayjs | null): string | undefined {
  return value?.format('YYYY-MM-DD')
}

function buildHrPayload(values: HrFormValues): HrFieldsPayload {
  return {
    employment_type_id: values.employment_type_id || null,
    job_level_id: values.job_level_id || null,
    job_family_id: values.job_family_id || null,
    manager_id: values.manager_id || null,
    work_location: values.work_location?.trim() || null,
    cost_center: values.cost_center?.trim() || null,
    contract_no: values.contract_no?.trim() || null,
    weekly_hours: values.weekly_hours ?? null,
    employment_nature: values.employment_nature || null,
    probation_started_at: toDate(values.probation_started_at),
    probation_ended_at: toDate(values.probation_ended_at),
    regularized_at: toDate(values.regularized_at),
    change_reason: values.change_reason?.trim() || null,
    remark: values.remark ?? '',
  }
}

function HrFieldsGroup({
  userOptions,
  dictionaries,
}: {
  userOptions: { label: string; value: string }[]
  dictionaries: Record<HrDictionaryCategory, HrDictionary[]>
}) {
  const dictOptions = (list: HrDictionary[]) =>
    list.map((item) => ({ label: item.name, value: item.id }))
  return (
    <>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="employment_type_id" label="雇佣类型">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={dictOptions(dictionaries.employment_type)}
              placeholder="选择雇佣类型"
            />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="job_level_id" label="岗位职级">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={dictOptions(dictionaries.job_level)}
              placeholder="选择岗位职级"
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="job_family_id" label="岗位序列">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={dictOptions(dictionaries.job_family)}
              placeholder="选择岗位序列"
            />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="manager_id" label="汇报上级">
            <Select
              allowClear
              showSearch
              optionFilterProp="label"
              options={userOptions}
              placeholder="选择汇报上级"
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name="work_location" label="工作地点">
            <Input maxLength={100} placeholder="例如：北京" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="cost_center" label="成本中心">
            <Input maxLength={64} placeholder="例如：CC-001" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="contract_no" label="合同编号">
            <Input maxLength={64} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name="employment_nature" label="用工性质">
            <Select allowClear options={EMPLOYMENT_NATURE_OPTIONS} placeholder="选择用工性质" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="weekly_hours" label="标准工时（小时/周）">
            <InputNumber min={0} max={168} step={1} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name="probation_started_at" label="试用期开始">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="probation_ended_at" label="试用期结束">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name="regularized_at" label="转正日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="change_reason" label="变动原因">
        <Input maxLength={255} />
      </Form.Item>
      <Form.Item name="remark" label="备注">
        <Input.TextArea rows={2} maxLength={2000} />
      </Form.Item>
    </>
  )
}

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
  const [dictionaries, setDictionaries] = useState<Record<HrDictionaryCategory, HrDictionary[]>>({
    employment_type: [],
    job_level: [],
    job_family: [],
  })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Employment | null>(null)
  const [transferring, setTransferring] = useState<Employment | null>(null)
  const [archiving, setArchiving] = useState<Employment | null>(null)
  const [dictionaryDrawerOpen, setDictionaryDrawerOpen] = useState(false)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editForm] = Form.useForm<EditFormValues>()
  const [transferForm] = Form.useForm<TransferFormValues>()
  const [archiveForm] = Form.useForm<ArchiveFormValues>()

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

  const loadDictionary = useCallback(async () => {
    try {
      const [employment_type, job_level, job_family] = await Promise.all([
        hrDictionariesApi.list('employment_type'),
        hrDictionariesApi.list('job_level'),
        hrDictionariesApi.list('job_family'),
      ])
      setDictionaries({ employment_type, job_level, job_family })
    } catch {
      // 字典加载失败不阻塞列表
    }
  }, [])

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
    void loadDictionary()
  }, [loadDictionary])

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
        started_at: toDate(values.started_at),
        ...buildHrPayload(values),
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
      started_at: record.started_at ? dayjs(record.started_at) : undefined,
      employment_type_id: record.employment_type_id ?? undefined,
      job_level_id: record.job_level_id ?? undefined,
      job_family_id: record.job_family_id ?? undefined,
      manager_id: record.manager_id ?? undefined,
      work_location: record.work_location ?? undefined,
      cost_center: record.cost_center ?? undefined,
      contract_no: record.contract_no ?? undefined,
      weekly_hours: record.weekly_hours ?? undefined,
      employment_nature: record.employment_nature ?? undefined,
      probation_started_at: record.probation_started_at
        ? dayjs(record.probation_started_at)
        : undefined,
      probation_ended_at: record.probation_ended_at
        ? dayjs(record.probation_ended_at)
        : undefined,
      regularized_at: record.regularized_at ? dayjs(record.regularized_at) : undefined,
      change_reason: record.change_reason ?? undefined,
      remark: record.remark || undefined,
    })
  }

  const handleEdit = async () => {
    if (!editing) return
    const values = await editForm.validateFields()
    setSaving(true)
    try {
      await employmentsApi.update(editing.id, {
        position: values.position?.trim(),
        started_at: toDate(values.started_at),
        ...buildHrPayload(values),
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
      change_type: 'transfer',
      employment_type_id: record.employment_type_id ?? undefined,
      job_level_id: record.job_level_id ?? undefined,
      job_family_id: record.job_family_id ?? undefined,
      manager_id: record.manager_id ?? undefined,
      work_location: record.work_location ?? undefined,
      cost_center: record.cost_center ?? undefined,
      contract_no: record.contract_no ?? undefined,
      weekly_hours: record.weekly_hours ?? undefined,
      employment_nature: record.employment_nature ?? undefined,
      probation_started_at: record.probation_started_at
        ? dayjs(record.probation_started_at)
        : undefined,
      probation_ended_at: record.probation_ended_at
        ? dayjs(record.probation_ended_at)
        : undefined,
      regularized_at: record.regularized_at ? dayjs(record.regularized_at) : undefined,
      change_reason: record.change_reason ?? undefined,
      remark: record.remark || undefined,
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
        started_at: toDate(values.started_at),
        change_type: values.change_type,
        ...buildHrPayload(values),
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

  const openArchive = (record: Employment) => {
    setArchiving(record)
    archiveForm.setFieldsValue({
      ended_at: dayjs(),
      termination_type: undefined,
      change_reason: undefined,
    })
  }

  const handleArchive = async () => {
    if (!archiving) return
    const values = await archiveForm.validateFields()
    setSaving(true)
    try {
      await employmentsApi.archive(archiving.id, {
        ended_at: toDate(values.ended_at),
        termination_type: values.termination_type || null,
        change_reason: values.change_reason?.trim() || null,
      })
      message.success('任职已结束')
      setArchiving(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    } finally {
      setSaving(false)
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
      width: 180,
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
      width: 140,
      render: (value: string | null) => value || '-',
    },
    {
      title: '岗位 / 职级',
      key: 'position_level',
      width: 160,
      render: (_: unknown, record: Employment) => (
        <div>
          <div className="resource-name">{record.position || '-'}</div>
          <div className="resource-desc">
            {[record.job_level_name, record.job_family_name].filter(Boolean).join(' / ') || '-'}
          </div>
        </div>
      ),
    },
    {
      title: '汇报上级',
      dataIndex: 'manager_name',
      key: 'manager_name',
      width: 120,
      render: (value: string | null) => value || '-',
    },
    {
      title: '雇佣类型',
      dataIndex: 'employment_type_name',
      key: 'employment_type_name',
      width: 100,
      render: (value: string | null) => value || '-',
    },
    {
      title: '状态',
      dataIndex: 'is_current',
      key: 'is_current',
      width: 90,
      render: (current: boolean, record: Employment) => (
        <Space direction="vertical" size={0}>
          {current ? (
            <Tag color="green" bordered={false}>
              当前
            </Tag>
          ) : (
            <Tag color="default" bordered={false}>
              历史
            </Tag>
          )}
          {record.termination_type && (
            <Tag color="red" bordered={false}>
              {TERMINATION_TYPE_OPTIONS.find((o) => o.value === record.termination_type)?.label ??
                record.termination_type}
            </Tag>
          )}
        </Space>
      ),
    },
    {
      title: '任职区间',
      key: 'period',
      width: 190,
      render: (_: unknown, record: Employment) =>
        `${record.started_at} ~ ${record.ended_at ?? '至今'}`,
    },
    ...(showActions
      ? [
          {
            title: '操作',
            key: 'actions',
            width: 220,
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
                  <Button type="link" size="small" onClick={() => openArchive(record)}>
                    结束任职
                  </Button>
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
        <Space>
          <Button icon={<IdcardOutlined />} onClick={() => setDictionaryDrawerOpen(true)}>
            HR 字典
          </Button>
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              新增任职
            </Button>
          )}
        </Space>
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
        width={720}
        forceRender
        destroyOnHidden
      >
        <Form<CreateFormValues> form={createForm} layout="vertical" requiredMark={false}>
          <Row gutter={12}>
            <Col span={12}>
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
            </Col>
            <Col span={12}>
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
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="position" label="岗位">
                <Input maxLength={100} placeholder="例如：客服专员" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="started_at" label="生效日期" extra="不选默认为今天。">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <HrFieldsGroup userOptions={userOptions} dictionaries={dictionaries} />
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
        width={720}
        forceRender
        destroyOnHidden
      >
        <Form<EditFormValues> form={editForm} layout="vertical" requiredMark={false}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="position" label="岗位">
                <Input maxLength={100} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="started_at" label="生效日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <HrFieldsGroup userOptions={userOptions} dictionaries={dictionaries} />
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
        width={720}
        forceRender
        destroyOnHidden
      >
        <Form<TransferFormValues> form={transferForm} layout="vertical" requiredMark={false}>
          <Row gutter={12}>
            <Col span={12}>
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
            </Col>
            <Col span={12}>
              <Form.Item name="change_type" label="变动类型">
                <Select options={CHANGE_TYPE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="position" label="新岗位" extra="留空沿用原岗位。">
                <Input maxLength={100} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="started_at"
                label="生效日期"
                extra="不选默认为今天；原任职结束日期为生效日期前一天。"
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <HrFieldsGroup userOptions={userOptions} dictionaries={dictionaries} />
        </Form>
      </Modal>

      <Modal
        title={
          archiving ? `结束任职：${archiving.user_display_name || archiving.user_name}` : '结束任职'
        }
        open={Boolean(archiving)}
        onOk={handleArchive}
        onCancel={() => setArchiving(null)}
        confirmLoading={saving}
        okText="确认结束"
        cancelText="取消"
        forceRender
        destroyOnHidden
      >
        <Form<ArchiveFormValues> form={archiveForm} layout="vertical" requiredMark={false}>
          <Form.Item name="ended_at" label="结束日期">
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="termination_type" label="离职类型">
            <Select allowClear options={TERMINATION_TYPE_OPTIONS} placeholder="选择离职类型" />
          </Form.Item>
          <Form.Item name="change_reason" label="离职原因">
            <Input.TextArea rows={2} maxLength={255} />
          </Form.Item>
        </Form>
      </Modal>

      <HrDictionariesDrawer
        open={dictionaryDrawerOpen}
        onClose={() => setDictionaryDrawerOpen(false)}
      />
    </div>
  )
}
