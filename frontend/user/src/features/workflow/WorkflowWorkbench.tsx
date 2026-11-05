import type { ApprovalContext, RunHistoryItem, WorkflowRunState, WorkflowSchema } from './types'
import ApprovalNotice from './components/ApprovalNotice'
import EmptyRunState from './components/EmptyRunState'
import ResultCard from './components/ResultCard'
import RunHistoryDrawer from './components/RunHistoryDrawer'
import StartInputForm from './components/StartInputForm'
import TraceTimeline from './components/TraceTimeline'
import WorkflowErrorCard from './components/WorkflowErrorCard'
import WorkflowHeader from './components/WorkflowHeader'

interface WorkflowWorkbenchProps {
  agentName: string
  schema: WorkflowSchema | null
  state: WorkflowRunState
  approvalContext: ApprovalContext
  submittingApproval: boolean
  runs: RunHistoryItem[]
  approvals: RunHistoryItem[]
  historyOpen: boolean
  onHistoryOpenChange: (open: boolean) => void
  onBack: () => void
  onRun: (inputs: Record<string, unknown>) => void
  onStop: () => void
  onApprove: (comment: string) => void
  onReject: (comment: string) => void
  onRefreshApproval: () => void
  onRetry: () => void
  onSelectHistoryRun?: (item: RunHistoryItem) => void
  onLoadError?: string | null
}

/** 工作台三栏视图：左入参面板 + 右轨迹/结果/审批/错误列 + 历史抽屉。 */
export default function WorkflowWorkbench(props: WorkflowWorkbenchProps) {
  const {
    agentName,
    schema,
    state,
    approvalContext,
    submittingApproval,
    runs,
    approvals,
    historyOpen,
    onHistoryOpenChange,
    onBack,
    onRun,
    onStop,
    onApprove,
    onReject,
    onRefreshApproval,
    onRetry,
    onSelectHistoryRun,
    onLoadError,
  } = props
  const hasTrace = state.nodeOrder.length > 0 || state.phase === 'running'
  return (
    <div className="wf-page">
      <WorkflowHeader
        agentName={agentName}
        onBack={onBack}
        onOpenHistory={() => onHistoryOpenChange(true)}
        approvalCount={approvals.length}
      />
      <div className="wf-body">
        <aside className="wf-panel">
          <div className="wf-intro">
            <h2 className="wf-intro__title">{schema?.name || '工作流入参'}</h2>
            {schema?.description ? <p className="wf-intro__desc">{schema.description}</p> : null}
          </div>
          {onLoadError ? (
            <div className="wf-error-card" style={{ marginTop: 0 }}>
              <div className="wf-error-card__head">入参加载失败</div>
              <p className="wf-error-card__message">{onLoadError}</p>
            </div>
          ) : (
            <StartInputForm schema={schema} running={state.phase === 'running'} onSubmit={onRun} />
          )}
        </aside>
        <main className="wf-main">
          <div className="wf-column">
            {!hasTrace ? <EmptyRunState /> : null}
            {hasTrace ? <TraceTimeline state={state} onStop={onStop} /> : null}
            {state.phase === 'success' && state.result ? <ResultCard output={state.result.output} /> : null}
            {state.phase === 'interrupted' && state.approval ? (
              <ApprovalNotice
                approval={state.approval}
                canApprove={approvalContext.canApprove}
                submitting={submittingApproval}
                onApprove={onApprove}
                onReject={onReject}
                onRefresh={onRefreshApproval}
              />
            ) : null}
            {state.phase === 'error' && state.error ? (
              <WorkflowErrorCard message={state.error.message} code={state.error.code} onRetry={onRetry} />
            ) : null}
          </div>
        </main>
      </div>
      <RunHistoryDrawer
        open={historyOpen}
        runs={runs}
        approvals={approvals}
        onClose={() => onHistoryOpenChange(false)}
        onSelectRun={onSelectHistoryRun ?? (() => onHistoryOpenChange(false))}
        onApproveFromHistory={onSelectHistoryRun}
      />
    </div>
  )
}
