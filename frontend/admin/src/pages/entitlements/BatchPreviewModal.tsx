import { Alert, DatePicker, Form, Input, Modal, Select, Space, Spin, Tag, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import type {
  EntitlementAuthType,
  EntitlementMode,
  EntitlementPreview,
  EntitlementView,
} from '../../api/entitlements'
import { OBJECT_TYPE_LABELS, STATUS_LABELS } from './EntitlementTable'

const { Text } = Typography

export interface BatchFormValues {
  reason: string
  auth_type: EntitlementAuthType
  period?: [Dayjs, Dayjs]
}

interface BatchPreviewModalProps {
  open: boolean
  mode: EntitlementMode
  preview: EntitlementPreview | null
  loading: boolean
  submitting: boolean
  onCancel: () => void
  onConfirm: (values: BatchFormValues) => void
}

function ViewList({ rows }: { rows: EntitlementView[] }) {
  return (
    <ul style={{ margin: 0, paddingLeft: 18 }}>
      {rows.map((row) => (
        <li key={`${row.object_type}:${row.object_id}`}>
          {row.name || '(未命名)'}
          <Tag style={{ marginLeft: 6 }}>
            {OBJECT_TYPE_LABELS[row.object_type as keyof typeof OBJECT_TYPE_LABELS] ??
              row.object_type}
          </Tag>
          <Text type="secondary">{STATUS_LABELS[row.status] ?? row.status}</Text>
        </li>
      ))}
    </ul>
  )
}

export default function BatchPreviewModal({
  open,
  mode,
  preview,
  loading,
  submitting,
  onCancel,
  onConfirm,
}: BatchPreviewModalProps) {
  const [form] = Form.useForm<BatchFormValues>()
  const isGrant = mode === 'grant'
  const addCount = preview?.add.length ?? 0
  const removeCount = preview?.remove.length ?? 0
  const unchangedCount = preview?.unchanged.length ?? 0
  const confirmable = isGrant ? addCount > 0 : removeCount > 0

  const handleOk = async () => {
    const values = await form.validateFields()
    onConfirm({
      reason: values.reason ?? '',
      auth_type: values.auth_type ?? 'FORMAL',
      period: values.period,
    })
  }

  return (
    <Modal
      open={open}
      title={isGrant ? '开通预览' : '取消开通预览'}
      width={640}
      okText="确认执行"
      cancelText="返回"
      okButtonProps={{ disabled: !confirmable || loading, loading: submitting }}
      onOk={handleOk}
      onCancel={onCancel}
      destroyOnClose
    >
      <Spin spinning={loading}>
        {isGrant ? (
          <>
            <Alert
              type="info"
              showIcon
              message={`将新增/恢复 ${addCount} 项，无变化 ${unchangedCount} 项`}
              style={{ marginBottom: 12 }}
            />
            {addCount > 0 && <ViewList rows={preview?.add ?? []} />}
          </>
        ) : (
          <>
            <Alert
              type="warning"
              showIcon
              message="取消后相关角色授权将失效，恢复开通后自动恢复；如需彻底清除请使用下架/清除"
              style={{ marginBottom: 12 }}
            />
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {(preview?.remove ?? []).map((item) => (
                <li key={`${item.view.object_type}:${item.view.object_id}`}>
                  <Space size={6} wrap>
                    {item.view.name || '(未命名)'}
                    <Tag color="orange">影响 {item.affected_role_grants} 项角色授权</Tag>
                    {item.affected_role_names.length > 0 && (
                      <Text type="secondary">{item.affected_role_names.join('、')}</Text>
                    )}
                  </Space>
                </li>
              ))}
            </ul>
          </>
        )}
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 16 }}
          initialValues={{ auth_type: 'FORMAL' }}
        >
          {isGrant && (
            <Space style={{ width: '100%' }} size={12}>
              <Form.Item name="auth_type" label="授权类型" style={{ marginBottom: 12 }}>
                <Select
                  style={{ width: 140 }}
                  options={[
                    { value: 'FORMAL', label: '正式' },
                    { value: 'TRIAL', label: '试用' },
                    { value: 'GIFT', label: '赠送' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="period"
                label="有效期（留空=立即生效且长期）"
                style={{ marginBottom: 12 }}
              >
                <DatePicker.RangePicker showTime style={{ width: 380 }} />
              </Form.Item>
            </Space>
          )}
          <Form.Item name="reason" label={isGrant ? '开通事由' : '取消原因'}>
            <Input.TextArea rows={2} maxLength={200} placeholder="将记录到权益备注与审计" />
          </Form.Item>
        </Form>
      </Spin>
    </Modal>
  )
}
