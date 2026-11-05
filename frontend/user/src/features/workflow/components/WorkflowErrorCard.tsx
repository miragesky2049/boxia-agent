import { useState } from 'react'
import { CloseCircleOutlined, ReloadOutlined } from '@ant-design/icons'

interface WorkflowErrorCardProps {
  message: string
  code?: string
  onRetry: () => void
}

/** 运行错误卡：面向用户的文案 + 可折叠的技术详情 + 重试。 */
export default function WorkflowErrorCard(props: WorkflowErrorCardProps) {
  const { message, code, onRetry } = props
  const [detail, setDetail] = useState(false)
  return (
    <div className="wf-error-card">
      <div className="wf-error-card__head">
        <CloseCircleOutlined />
        运行失败
      </div>
      <p className="wf-error-card__message">{message}</p>
      {detail ? <pre className="wf-error-card__detail">{code ? `错误代码：${code}` : '无更多技术信息'}</pre> : null}
      <div className="wf-error-card__actions">
        <button type="button" className="wf-btn wf-btn--primary" onClick={onRetry}>
          <ReloadOutlined />
          重试
        </button>
        <button type="button" className="wf-link-btn" onClick={() => setDetail((v) => !v)}>
          {detail ? '收起技术详情' : '查看技术详情'}
        </button>
      </div>
    </div>
  )
}
