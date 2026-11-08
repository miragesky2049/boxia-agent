import { Button, Drawer, Input, Space, Tag, Typography } from 'antd'
import type { ApprovalInterruptPayload } from '../../../api/apps'

// 人审审批抽屉（B11）：展示中断负载并提交通过/拒绝
export function ApprovalDrawer({
  open,
  payload,
  approver,
  comment,
  onApproverChange,
  onCommentChange,
  onClose,
  onSubmit,
}: {
  open: boolean
  payload: ApprovalInterruptPayload | null
  approver: string
  comment: string
  onApproverChange: (value: string) => void
  onCommentChange: (value: string) => void
  onClose: () => void
  onSubmit: (approved: boolean) => void
}) {
  return (
    <Drawer
      title={payload ? `审批：${payload.node_title || payload.node_id}` : '审批'}
      open={open}
      onClose={onClose}
      width="min(480px, 92vw)"
    >
      {payload && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {payload.assignee_role && (
            <div>
              <Typography.Text type="secondary">审批人角色</Typography.Text>
              <div>
                <Tag color="orange">{payload.assignee_role}</Tag>
              </div>
            </div>
          )}
          {payload.instructions && (
            <div>
              <Typography.Text type="secondary">审批说明</Typography.Text>
              <div style={{ padding: 8, background: '#fafafa', borderRadius: 6, fontSize: 13 }}>
                {payload.instructions}
              </div>
            </div>
          )}
          {payload.snapshot && (
            <div>
              <Typography.Text type="secondary">节点输入快照</Typography.Text>
              <pre
                style={{
                  margin: 0,
                  padding: 8,
                  background: '#fafafa',
                  borderRadius: 6,
                  fontSize: 11,
                  maxHeight: 200,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {JSON.stringify(payload.snapshot, null, 2)}
              </pre>
            </div>
          )}
          <div>
            <Typography.Text type="secondary">审批人</Typography.Text>
            <Input
              value={approver}
              onChange={(e) => onApproverChange(e.target.value)}
              placeholder="你的名字（默认 admin）"
            />
          </div>
          <div>
            <Typography.Text type="secondary">审批意见</Typography.Text>
            <Input.TextArea
              rows={3}
              value={comment}
              onChange={(e) => onCommentChange(e.target.value)}
              placeholder="通过 / 拒绝的原因"
            />
          </div>
          <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
            <Button danger onClick={() => onSubmit(false)}>
              拒绝
            </Button>
            <Button type="primary" onClick={() => onSubmit(true)}>
              通过
            </Button>
          </Space>
        </Space>
      )}
    </Drawer>
  )
}
