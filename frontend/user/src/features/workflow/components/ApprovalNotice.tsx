import { useState } from 'react'
import { CheckCircleOutlined, ClockCircleOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import type { ApprovalPayload } from '../types'

function formatSnapshot(snapshot: unknown): string {
  if (snapshot === null || snapshot === undefined) return ''
  if (typeof snapshot === 'string') return snapshot
  try {
    return JSON.stringify(snapshot, null, 2)
  } catch {
    return String(snapshot)
  }
}

interface ApprovalNoticeProps {
  approval: ApprovalPayload
  canApprove: boolean
  submitting: boolean
  onApprove: (comment: string) => void
  onReject: (comment: string) => void
  onRefresh: () => void
}

/** 人审卡：可审批角色给出批准/拒绝操作，其余角色降级为纯等待态。 */
export default function ApprovalNotice(props: ApprovalNoticeProps) {
  const { approval, canApprove, submitting, onApprove, onReject, onRefresh } = props
  const [comment, setComment] = useState('')
  const snapshotText = formatSnapshot(approval.snapshot)
  if (!canApprove) {
    return (
      <div className="wf-approval">
        <div className="wf-approval__head">
          <SafetyCertificateOutlined />
          人工审批
        </div>
        <div className="wf-approval__node">{approval.node_title || approval.node_id || '审批节点'}</div>
        <div className="wf-approval__waiting">
          <span className="wf-approval__waiting-icon">
            <ClockCircleOutlined />
          </span>
          <span>
            流程已暂停，等待「{approval.assignee_role || '审批'}」角色处理。
            {approval.instructions ? ` ${approval.instructions}` : ''}
          </span>
          <button type="button" className="wf-approval__refresh" onClick={onRefresh} disabled={submitting}>
            刷新状态
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className="wf-approval">
      <div className="wf-approval__head">
        <SafetyCertificateOutlined />
        人工审批 · 等待你的决定
      </div>
      <div className="wf-approval__node">{approval.node_title || approval.node_id || '审批节点'}</div>
      {approval.instructions ? <p className="wf-approval__instructions">{approval.instructions}</p> : null}
      {snapshotText ? <pre className="wf-approval__snapshot">{snapshotText}</pre> : null}
      <textarea
        className="wf-approval__comment"
        value={comment}
        placeholder="审批意见（选填，会随审批结果写入运行记录）"
        maxLength={2000}
        onChange={(e) => setComment(e.target.value)}
      />
      <div className="wf-approval__actions">
        <button
          type="button"
          className="wf-btn wf-btn--danger-ghost"
          disabled={submitting}
          onClick={() => onReject(comment)}
        >
          拒绝
        </button>
        <button
          type="button"
          className="wf-btn wf-btn--approve"
          disabled={submitting}
          onClick={() => onApprove(comment)}
        >
          <CheckCircleOutlined />
          {submitting ? '提交中…' : '批准并继续'}
        </button>
      </div>
    </div>
  )
}
