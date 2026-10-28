import { ApartmentOutlined, PlayCircleOutlined, PlusOutlined, StopOutlined, ToolOutlined } from '@ant-design/icons'
import type { ReactElement } from 'react'
import type { WorkflowNodeType } from '../store/workflowStore'

const ITEMS: Array<{
  type: WorkflowNodeType
  label: string
  desc: string
  color: string
  icon: ReactElement
}> = [
  { type: 'start', label: 'Start', desc: '工作流入口', color: '#52c41a', icon: <PlayCircleOutlined /> },
  { type: 'llm', label: 'LLM', desc: '调用大模型', color: '#1677ff', icon: <ApartmentOutlined /> },
  { type: 'tool', label: 'Tool', desc: '调用已注册工具', color: '#fa8c16', icon: <ToolOutlined /> },
  { type: 'end', label: 'End', desc: '工作流出口', color: '#722ed1', icon: <StopOutlined /> },
]

interface Props {
  onAdd: (type: WorkflowNodeType) => void
}

export function NodePalette({ onAdd }: Props) {
  return (
    <div style={{ width: 200, borderRight: '1px solid #f0f0f0', padding: 12, background: '#fafafa' }}>
      <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8 }}>节点库</div>
      {ITEMS.map((item) => (
        <div
          key={item.type}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 10px',
            marginBottom: 6,
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            cursor: 'pointer',
          }}
          onClick={() => onAdd(item.type)}
        >
          <span style={{ color: item.color, fontSize: 16 }}>{item.icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: '#262626' }}>
              {item.label}
            </div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>{item.desc}</div>
          </div>
          <PlusOutlined style={{ color: '#bfbfbf' }} />
        </div>
      ))}
    </div>
  )
}
