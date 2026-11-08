import { Input, Modal, Tag } from 'antd'

// 卡片「⋯」重命名弹窗（N9-07）
export function RenameNodeModal({
  target,
  onChange,
  onConfirm,
  onCancel,
}: {
  target: { nodeId: string; value: string } | null
  onChange: (value: string) => void
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal
      title="重命名节点"
      open={Boolean(target)}
      onOk={onConfirm}
      onCancel={onCancel}
      okText="保存"
      cancelText="取消"
    >
      <Input
        autoFocus
        maxLength={60}
        placeholder="节点名称"
        value={target?.value ?? ''}
        onChange={(e) => onChange(e.target.value)}
        onPressEnter={onConfirm}
      />
    </Modal>
  )
}

// 删除节点确认弹窗（U-S3）：单节点与批量共用
export function DeleteNodeModal({
  open,
  targetIds,
  selectedNodeId,
  selectedNodeTitle,
  onConfirm,
  onCancel,
}: {
  open: boolean
  targetIds: string[]
  selectedNodeId: string | null
  selectedNodeTitle?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <Modal
      title={targetIds.length > 1 ? '批量删除节点' : '删除节点'}
      open={open}
      onOk={onConfirm}
      onCancel={onCancel}
      okText="删除"
      okButtonProps={{ danger: true }}
      cancelText="取消"
    >
      <div>
        {targetIds.length > 1 ? (
          <span>
            确定要删除选中的 <Tag color="blue">{targetIds.length}</Tag> 个节点吗？
          </span>
        ) : (
          <span>
            确定要删除节点{' '}
            <Tag color="blue">{selectedNodeTitle || targetIds[0] || selectedNodeId}</Tag> 吗？
          </span>
        )}
        <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
          与该节点相连的所有连线将一并删除，此操作不可撤销。
        </div>
      </div>
    </Modal>
  )
}
