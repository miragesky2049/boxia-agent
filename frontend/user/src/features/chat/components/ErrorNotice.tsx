import { ExclamationCircleFilled, ReloadOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { MessageError } from '../types'

interface ErrorNoticeProps {
  error: MessageError
  onRetry?: () => void
}

export function ErrorNotice({ error, onRetry }: ErrorNoticeProps) {
  const [showDetail, setShowDetail] = useState(false)

  return (
    <div className="lc-error" role="alert">
      <ExclamationCircleFilled className="lc-error__icon" />
      <div className="lc-error__body">
        <div className="lc-error__message">{error.message}</div>
        <div className="lc-error__actions">
          {onRetry && (
            <button type="button" className="lc-btn lc-btn--ghost" onClick={onRetry}>
              <ReloadOutlined />
              <span>重试</span>
            </button>
          )}
          {error.detail && (
            <button
              type="button"
              className="lc-link-btn"
              onClick={() => setShowDetail((prev) => !prev)}
            >
              {showDetail ? '收起技术细节' : '查看技术细节'}
            </button>
          )}
        </div>
        {showDetail && error.detail && (
          <pre className="lc-error__detail">{error.detail}</pre>
        )}
      </div>
    </div>
  )
}
