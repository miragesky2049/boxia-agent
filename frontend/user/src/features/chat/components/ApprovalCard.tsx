import { CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { ApprovalSpec } from '../types'

interface ApprovalCardProps {
  approval: ApprovalSpec
  onDecision?: (approved: boolean, comment: string) => void
}

/** 0074 PRD F10：敏感工具审批卡——展示待执行调用，批准/拒绝后续跑。 */
export function ApprovalCard({ approval, onDecision }: ApprovalCardProps) {
  const [comment, setComment] = useState('')
  const [decided, setDecided] = useState<'approved' | 'rejected' | null>(
    approval.submitted ?? null,
  )

  const submit = (approved: boolean) => {
    if (decided) return
    const reason = comment.trim()
    onDecision?.(approved, reason)
    setDecided(approved ? 'approved' : 'rejected')
  }

  if (decided) {
    return (
      <div className="lc-approval is-decided">
        <span className={`lc-approval__icon${decided === 'approved' ? ' is-ok' : ' is-no'}`}>
          {decided === 'approved' ? <CheckOutlined /> : <CloseOutlined />}
        </span>
        <span>{decided === 'approved' ? '已批准执行' : '已拒绝执行'}</span>
      </div>
    )
  }

  return (
    <div className="lc-approval">
      <div className="lc-approval__title">需要你的审批</div>
      <div className="lc-approval__desc">智能体请求执行以下操作，批准前不会真正运行：</div>
      <ul className="lc-approval__calls">
        {approval.calls.map((call) => (
          <li key={call.id} className="lc-approval__call">
            <span className="lc-approval__name">{call.name}</span>
            {call.arguments && <code className="lc-approval__args">{call.arguments}</code>}
          </li>
        ))}
      </ul>

      <input
        className="lc-approval__input"
        value={comment}
        placeholder="审批意见（可选，拒绝时建议说明原因）…"
        onChange={(event) => setComment(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') submit(true)
        }}
      />

      <div className="lc-approval__footer">
        <button type="button" className="lc-btn lc-btn--primary" onClick={() => submit(true)}>
          批准执行
        </button>
        <button type="button" className="lc-btn" onClick={() => submit(false)}>
          拒绝
        </button>
      </div>
    </div>
  )
}
