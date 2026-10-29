import {
  ApartmentOutlined,
  ApiOutlined,
  BranchesOutlined,
  ClusterOutlined,
  CodeOutlined,
  FileSearchOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  StopOutlined,
  ToolOutlined,
  UserOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import type { ReactElement } from 'react'
import type { NodeType } from '../store/appStore'

export const APP_NODE_DND_MIME = 'application/app-node-type'

const ITEMS: Array<{
  type: NodeType
  label: string
  desc: string
  color: string
  icon: ReactElement
}> = [
  { type: 'start', label: '开始', desc: '工作流入口', color: '#52c41a', icon: <PlayCircleOutlined /> },
  { type: 'llm', label: 'LLM', desc: '调用大模型', color: '#1677ff', icon: <ApartmentOutlined /> },
  { type: 'retrieval', label: '检索', desc: 'RAG 知识库检索', color: '#2f54eb', icon: <FileSearchOutlined /> },
  { type: 'branch', label: '条件分支', desc: '按条件路由', color: '#faad14', icon: <BranchesOutlined /> },
  { type: 'tool', label: '工具', desc: '调用已注册工具', color: '#fa8c16', icon: <ToolOutlined /> },
  { type: 'template', label: '模板', desc: '文本渲染', color: '#13c2c2', icon: <CodeOutlined /> },
  { type: 'http', label: 'HTTP', desc: '发 HTTP 请求', color: '#eb2f96', icon: <ApiOutlined /> },
  { type: 'human_task', label: '人审', desc: '暂停等待人工审批', color: '#fa541c', icon: <UserOutlined /> },
  { type: 'subgraph', label: '子图', desc: '嵌套调用另一个应用', color: '#08979c', icon: <ClusterOutlined /> },
  { type: 'end', label: '结束', desc: '工作流出口', color: '#722ed1', icon: <StopOutlined /> },
]

const STICKY_ITEM = {
  type: 'sticky' as NodeType,
  label: '注释便签',
  desc: '画布上的黄色便签',
  color: '#faad14',
  icon: <FileTextOutlined />,
}

interface Props {
  onAdd: (type: NodeType) => void
}

export function NodePalette({ onAdd }: Props) {
  return (
    <div
      style={{
        width: 200,
        borderRight: '1px solid #f0f0f0',
        background: '#fafafa',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      <div style={{ fontSize: 12, color: '#8c8c8c', padding: '12px 12px 8px', flexShrink: 0 }}>
        节点库（拖拽到画布）
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 12px' }}>
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
            event.dataTransfer.setData(APP_NODE_DND_MIME, item.type)
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
      <div style={{ fontSize: 11, color: '#bfbfbf', margin: '8px 0 4px', paddingLeft: 4 }}>画布元素</div>
        <div
          draggable
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '8px 10px',
            marginBottom: 6,
            background: '#fffbe6',
            border: '1px solid #ffe58f',
            borderRadius: 6,
            cursor: 'grab',
          }}
          onDragStart={(event) => {
            event.dataTransfer.setData(APP_NODE_DND_MIME, STICKY_ITEM.type)
            event.dataTransfer.effectAllowed = 'move'
          }}
          onClick={() => onAdd(STICKY_ITEM.type)}
        >
          <span style={{ color: STICKY_ITEM.color, fontSize: 16 }}>{STICKY_ITEM.icon}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: '#262626' }}>{STICKY_ITEM.label}</div>
            <div style={{ fontSize: 11, color: '#8c8c8c' }}>{STICKY_ITEM.desc}</div>
          </div>
          <PlusOutlined style={{ color: '#bfbfbf' }} />
        </div>
      </div>
    </div>
  )
}
