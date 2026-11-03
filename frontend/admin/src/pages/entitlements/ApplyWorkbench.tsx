import {
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  getOpsDashboardStats,
  listOpsPendingApplies,
  passApply,
  rejectApply,
  type ApplyRow,
  type ApplyType,
  type OpsDashboardStats,
} from '../../api/entitlements'
import { fetchPublicTenants } from '../../api/tenant'
import type { Tenant } from '../../api/types'

const APPLY_TYPE_LABELS: Record<ApplyType, string> = {
  TRIAL: '试用',
  BUY: '购买',
}

const APPLY_TYPE_COLORS: Record<ApplyType, string> = {
  TRIAL: 'orange',
  BUY: 'blue',
}

interface PassFormValues {
  audit_msg: string
  contract_no: string
  grant_start_time?: dayjs.Dayjs
  grant_expire_time?: dayjs.Dayjs
  grant_quota_text: string
}

interface RejectFormValues {
  audit_msg: string
}

/** 申请审批工作台：市场申请单的运营审核闭环（P2-6），后端以 PlatformAdminDep 收口。 */
export default function ApplyWorkbench() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<ApplyRow[]>([])
  const [stats, setStats] = useState<OpsDashboardStats | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])

  const [passing, setPassing] = useState<ApplyRow | null>(null)
  const [rejecting, setRejecting] = useState<ApplyRow | null>(null)
  const [saving, setSaving] = useState(false)
  const [passForm] = Form.useForm<PassFormValues>()
  const [rejectForm] = Form.useForm<RejectFormValues>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [applyRows, dashboard] = await Promise.all([
        listOpsPendingApplies(),
        getOpsDashboardStats(),
      ])
      setRows(applyRows)
      setStats(dashboard)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载申请队列失败')
    } finally {
      setLoading(false)
    }
  }, [message])

  useEffect(() => {
    void load()
    fetchPublicTenants()
      .then(setTenants)
      .catch(() => {})
  }, [load])

  const tenantNameMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const t of tenants) map.set(t.id, t.name)
    return map
  }, [tenants])

  const openPass = (record: ApplyRow) => {
    setPassing(record)
    passForm.setFieldsValue({
      audit_msg: '',
      contract_no: '',
      grant_start_time: undefined,
      grant_expire_time: undefined,
      grant_quota_text: '',
    })
  }

  const handlePass = async () => {
    if (!passing) return
    let values: PassFormValues
    try {
      values = await passForm.validateFields()
    } catch {
      return
    }
    let grantQuota: Record<string, unknown> | undefined
    if (values.grant_quota_text.trim()) {
      try {
        grantQuota = JSON.parse(values.grant_quota_text) as Record<string, unknown>
      } catch {
        message.error('配额 JSON 不合法')
        return
      }
    }
    setSaving(true)
    try {
      const result = await passApply(passing.id, {
        audit_msg: values.audit_msg,
        contract_no: values.contract_no,
        grant_start_time: values.grant_start_time
          ? values.grant_start_time.toISOString()
          : undefined,
        grant_expire_time: values.grant_expire_time
          ? values.grant_expire_time.toISOString()
          : undefined,
        grant_quota: grantQuota,
      })
      message.success(
        result.instance_id
          ? '已通过并开通，生成权益实例'
          : '已通过，进入待开通列表（未填开通参数）',
      )
      setPassing(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '通过失败')
    } finally {
      setSaving(false)
    }
  }

  const openReject = (record: ApplyRow) => {
    setRejecting(record)
    rejectForm.setFieldsValue({ audit_msg: '' })
  }

  const handleReject = async () => {
    if (!rejecting) return
    let values: RejectFormValues
    try {
      values = await rejectForm.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      await rejectApply(rejecting.id, values.audit_msg)
      message.success('已拒绝该申请')
      setRejecting(null)
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '拒绝失败')
    } finally {
      setSaving(false)
    }
  }

  const columns: ColumnsType<ApplyRow> = [
    {
      title: '应用',
      dataIndex: 'application_name',
      render: (name: string, record) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {record.id.slice(0, 8)}…
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '租户',
      dataIndex: 'tenant_id',
      width: 160,
      render: (tid: string) => tenantNameMap.get(tid) ?? tid.slice(0, 8) + '…',
    },
    {
      title: '类型',
      dataIndex: 'apply_type',
      width: 80,
      render: (t: ApplyType) => <Tag color={APPLY_TYPE_COLORS[t]}>{APPLY_TYPE_LABELS[t]}</Tag>,
    },
    { title: '联系方式', dataIndex: 'contact', width: 160, ellipsis: true },
    { title: '期望说明', dataIndex: 'expect_text', ellipsis: true },
    {
      title: '提交时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: string) => dayjs(v).format('MM-DD HH:mm'),
    },
    {
      title: '销售',
      dataIndex: 'sales_username',
      width: 110,
      render: (u: string | null) => u ?? <Typography.Text type="secondary">未认领</Typography.Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => openPass(record)}>
            通过
          </Button>
          <Button type="link" size="small" danger onClick={() => openReject(record)}>
            拒绝
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="page-card">
      <Typography.Title level={4} style={{ margin: 0 }}>
        申请审批工作台
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
        租户在应用市场提交的开通申请在此审核；通过时填写开通参数将直接生成权益，否则进入待开通列表。
      </Typography.Paragraph>

      {stats && (
        <Row gutter={12} style={{ marginBottom: 16 }}>
          <Col span={3}>
            <Card size="small">
              <Statistic title="待审核" value={stats.pending_count} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="通过待开通" value={stats.pass_pending_count} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="已完成" value={stats.finished_count} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="已拒绝" value={stats.rejected_count} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="近7天申请" value={stats.last_7d_count} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="生效中权益" value={stats.active_grants} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="待生效" value={stats.wait_effect_grants} />
            </Card>
          </Col>
          <Col span={3}>
            <Card size="small">
              <Statistic title="已过期" value={stats.expired_grants} />
            </Card>
          </Col>
        </Row>
      )}

      <Table<ApplyRow>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={{ pageSize: 20, size: 'small' }}
        locale={{ emptyText: '暂无待审核申请' }}
      />

      <Modal
        open={!!passing}
        title={passing ? `通过申请：${passing.application_name}` : '通过申请'}
        onCancel={() => setPassing(null)}
        onOk={() => void handlePass()}
        okText="确认通过"
        confirmLoading={saving}
      >
        <Form form={passForm} layout="vertical">
          <Form.Item label="审核备注" name="audit_msg">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="合同编号" name="contract_no">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item
            label="开通开始时间"
            name="grant_start_time"
            extra="填写后将同时开通授权并生成权益；留空则仅通过、进入待开通列表"
          >
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="开通到期时间" name="grant_expire_time">
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="配额（JSON）" name="grant_quota_text">
            <Input.TextArea
              rows={3}
              style={{ fontFamily: 'monospace' }}
              placeholder='{"calls": 1000}'
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={!!rejecting}
        title={rejecting ? `拒绝申请：${rejecting.application_name}` : '拒绝申请'}
        onCancel={() => setRejecting(null)}
        onOk={() => void handleReject()}
        okText="确认拒绝"
        okButtonProps={{ danger: true }}
        confirmLoading={saving}
      >
        <Form form={rejectForm} layout="vertical">
          <Form.Item
            label="拒绝原因"
            name="audit_msg"
            rules={[{ required: true, message: '请填写拒绝原因' }]}
          >
            <Input.TextArea rows={3} placeholder="将反馈给申请租户" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
