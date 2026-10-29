import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react'
import { PlusOutlined } from '@ant-design/icons'
import { Dropdown, App } from 'antd'
import { useState } from 'react'
import type { NodeType } from '../store/appStore'
import { useAppStore } from '../store/appStore'

const INSERTABLE_TYPES: Array<{ type: NodeType; label: string }> = [
  { type: 'llm', label: 'LLM' },
  { type: 'tool', label: '工具' },
  { type: 'template', label: '模板' },
  { type: 'http', label: 'HTTP' },
  { type: 'retrieval', label: '检索' },
  { type: 'branch', label: '条件分支' },
  { type: 'human_task', label: '人审' },
  { type: 'subgraph', label: '子图' },
]

/** 自定义连线：贝塞尔曲线 + 中点悬浮「+」按钮，点击弹出节点类型菜单 */
export function EdgeWithPlus(props: EdgeProps) {
  const { id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected } = props
  const [path, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })
  const [hover, setHover] = useState(false)
  const insertNodeBetween = useAppStore((s) => s.insertNodeBetween)
  const { message } = App.useApp()

  const handleSelect = (type: NodeType) => {
    insertNodeBetween(source, target, type)
    message.success(`已插入「${INSERTABLE_TYPES.find((t) => t.type === type)?.label ?? type}」节点`)
  }

  const show = hover || selected

  return (
    <>
      <BaseEdge id={id} path={path} style={{ stroke: selected ? '#1677ff' : '#bfbfbf', strokeWidth: selected ? 2 : 1.5 }} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: 'all',
            opacity: show ? 1 : 0,
            transition: 'opacity 0.15s',
          }}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
        >
          <Dropdown
            menu={{
              items: INSERTABLE_TYPES.map((t) => ({ key: t.type, label: t.label })),
              onClick: ({ key }) => handleSelect(key as NodeType),
            }}
            trigger={['click']}
            placement="bottom"
          >
            <div
              style={{
                width: 22,
                height: 22,
                borderRadius: '50%',
                background: '#fff',
                border: '1px solid #1677ff',
                color: '#1677ff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                boxShadow: '0 2px 6px rgba(0,0,0,0.15)',
                fontSize: 12,
              }}
            >
              <PlusOutlined />
            </div>
          </Dropdown>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}
