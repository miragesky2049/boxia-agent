import { ArrowLeftOutlined, HistoryOutlined } from '@ant-design/icons'

interface WorkflowHeaderProps {
  agentName: string
  onBack: () => void
  onOpenHistory: () => void
  approvalCount: number
}

/** 工作台顶栏：返回、应用身份、历史入口。 */
export default function WorkflowHeader(props: WorkflowHeaderProps) {
  const { agentName, onBack, onOpenHistory, approvalCount } = props
  const initial = agentName.slice(0, 1) || 'A'
  return (
    <header className="wf-header">
      <button type="button" className="wf-header__back" onClick={onBack} aria-label="返回">
        <ArrowLeftOutlined />
      </button>
      <div className="wf-header__agent">
        <div className="wf-agent-avatar" aria-hidden="true">
          {initial}
        </div>
        <div className="wf-header__meta">
          <div className="wf-header__name">{agentName}</div>
          <div className="wf-header__kind">工作流应用</div>
        </div>
      </div>
      <div className="wf-header__actions">
        <button type="button" className="wf-btn wf-btn--ghost" onClick={onOpenHistory}>
          <HistoryOutlined />
          运行历史
          {approvalCount > 0 ? <span className="wf-drawer__tab-badge">{approvalCount}</span> : null}
        </button>
      </div>
    </header>
  )
}
