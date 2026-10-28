import {
  ApartmentOutlined,
  ApiOutlined,
  BranchesOutlined,
  CodeOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  StopOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import type { ReactElement } from 'react'
import type { V4NodeType } from '../store/appStore'

export const V4_NODE_DND_MIME = 'application/v4-node-type'

const ITEMS: Array<{
  type: V4NodeType
  label: string
  desc: string
  color: string
  icon: ReactElement
}> = [
  { type: 'start', label: '开始', desc: '工作流入口', color: '#52c41a', icon: <PlayCircleOutlined /> },
  { type: 'llm', label: 'LLM', desc: '调用大模型', color: '#1677ff', icon: <ApartmentOutlined /> },
  { type: 'branch', label: '条件分支', desc: '按条件路由', color: '#faad14', icon: <BranchesOutlined /> },
  { type: 'tool', label: '工具', desc: '调用已注册工具', color: '#fa8c16', icon: <ToolOutlined /> },
  { type: 'template', label: '模板', desc: '文本渲染', color: '#13c2c2', icon: <CodeOutlined /> },
  { type: 'http', label: 'HTTP', desc: '发 HTTP 请求', color: '#eb2f96', icon: <ApiOutlined /> },
  { type: 'end', label: '结束', desc: '工作流出口', color: '#722ed1', icon: <StopOutlined /> },
]

interface Props {
  onAdd: (type: V4NodeType) => void
}

export function NodePalette({ onAdd }: Props) {
  return (
    <div style={{ width: 200, borderRight: '1px solid #f0f0f0', padding: 12, background: '#fafafa' }}>
      <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8 }}>节点库（拖拽到画布）</div>
      {ITEMS.map((item) => (
        <div
          key={item.type}
          draggable
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 10px',
            marginBottom: 6,
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            cursor: 'grab',
          }}
          onDragStart={(event) => {
            event.dataTransfer.setData(V4_NODE_DND_MIME, item.type)
            event.dataTransfer.effectAllowed = 'move'
          }}
          onClick={() => onAdd(item.type)}
        >
          <span style={{ color: item.color, fontSize: 16 }}>{item.icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: '#262626' }}>{item.label}</div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>{item.desc}</div>
          </div>
          <PlusOutlined style={{ color: '#bfbfbf' }} />
        </div>
      ))}
    </div>
  )
}
