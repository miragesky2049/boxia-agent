import { StopOutlined } from '@ant-design/icons'
import type { WorkflowRunState } from '../types'
import TraceNodeCard from './TraceNodeCard'

interface TraceTimelineProps {
  state: WorkflowRunState
  onStop?: () => void
}

/** 本次运行轨迹：头部状态条 + 节点时间线。 */
export default function TraceTimeline(props: TraceTimelineProps) {
  const { state, onStop } = props
  const running = state.phase === 'running'
  return (
    <div className="wf-trace">
      <div className="wf-trace__head">
        <span className="wf-trace__run-label">本次运行</span>
        <span className={`wf-status${running ? ' is-running' : ''}`}>
          {running ? (
            <>
              <span className="wf-spinner" aria-hidden="true" />
              执行中
            </>
          ) : state.phase === 'interrupted' ? (
            '等待审批'
          ) : state.phase === 'success' ? (
            '已完成'
          ) : (
            '已结束'
          )}
        </span>
        {running && onStop ? (
          <button type="button" className="wf-btn wf-btn--ghost wf-trace__stop" onClick={onStop}>
            <StopOutlined />
            停止
          </button>
        ) : null}
      </div>
      <div className="wf-timeline">
        {state.nodeOrder.map((nodeId) => (
          <TraceNodeCard key={nodeId} node={state.nodes[nodeId]} />
        ))}
      </div>
    </div>
  )
}
