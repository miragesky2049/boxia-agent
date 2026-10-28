import { Handle, Position, type NodeProps } from '@xyflow/react'
import { ApartmentOutlined, PlayCircleOutlined, ToolOutlined, StopOutlined } from '@ant-design/icons'
import type { ReactElement } from 'react'
import type { WorkflowNodeData, WorkflowNodeType } from '../../store/workflowStore'

const TYPE_META: Record<
  WorkflowNodeType,
  { color: string; icon: ReactElement; label: string }
> = {
  start: { color: '#52c41a', icon: <PlayCircleOutlined />, label: 'Start' },
  llm: { color: '#1677ff', icon: <ApartmentOutlined />, label: 'LLM' },
  tool: { color: '#fa8c16', icon: <ToolOutlined />, label: 'Tool' },
  end: { color: '#722ed1', icon: <StopOutlined />, label: 'End' },
}

const DEBUG_BORDER: Record<string, string> = {
  running: '#faad14',
  success: '#52c41a',
  error: '#ff4d4f',
}

export function WorkflowCanvasNode({ data, selected }: NodeProps) {
  const nodeData = data as WorkflowNodeData
  const meta = TYPE_META[nodeData.nodeType]
  const hasInput = nodeData.nodeType !== 'start'
  const hasOutput = nodeData.nodeType !== 'end'
  const debugStatus = (nodeData as WorkflowNodeData & { debugStatus?: string }).debugStatus
  const borderColor = debugStatus ? DEBUG_BORDER[debugStatus] ?? undefined : undefined
  const border = borderColor ?? (selected ? meta.color : '#d9d9d9')
  const isRunning = debugStatus === 'running'

  return (
    <div
      style={{
        minWidth: 160,
        maxWidth: 220,
        padding: '10px 14px',
        borderRadius: 8,
        background: '#fff',
        border: `2px solid ${border}`,
        boxShadow: isRunning
          ? '0 0 0 4px rgba(250, 173, 20, 0.25)'
          : selected
            ? `0 0 0 3px ${meta.color}33`
            : '0 1px 4px rgba(0,0,0,0.08)',
        opacity: debugStatus === 'pending' ? 0.6 : 1,
      }}
    >
      {hasInput && <Handle type="target" position={Position.Left} />}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: meta.color, fontSize: 16 }}>{meta.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, color: '#999' }}>{meta.label}</div>
          <div style={{ fontSize: 13, fontWeight: 500, color: '#262626' }}>
            {nodeData.label}
          </div>
        </div>
        {isRunning && (
          <span style={{ fontSize: 11, color: '#faad14' }}>运行中</span>
        )}
      </div>
      {hasOutput && <Handle type="source" position={Position.Right} />}
    </div>
  )
}
