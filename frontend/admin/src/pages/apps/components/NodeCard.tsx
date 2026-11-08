import { useState } from 'react'
import { Dropdown } from 'antd'
import { MoreOutlined } from '@ant-design/icons'
import { NodeIcon } from './NodeIcon'
import { buildNodeSubtitle } from './nodeSubtitle'
import type { RunNodeStatus } from './nodeStatus'
import { CANVAS_TOKENS } from '../canvas/tokens'
import { typeShortLabel } from '../canvas/metadata/chatflowStart'
import type { FlowType } from '../../../api/apps'

export interface NodeCardAction {
  key: string
  label: string
  danger?: boolean
  disabled?: boolean
  onClick: () => void
}

export interface DynamicOutputPort {
  portID: string
  label: string
}

interface NodeCardProps {
  typeKey: string
  color: string
  icon?: string
  title: string
  config?: Record<string, any>
  subtitleHint?: string
  selected?: boolean
  runStatus?: RunNodeStatus
  width?: number
  onDoubleClick?: () => void
  onAddNext?: () => void
  actions?: NodeCardAction[]
  children?: React.ReactNode
  dynamicOutputs?: DynamicOutputPort[]
  // 对话流开始节点的「输入」芯片行（对齐 Coze：str:USER_INPUT / str:CONVERSATION_NAME）
  inputChips?: Array<{ type: string; name: string }>
  flowType?: FlowType
}

// 与 Coze 对齐的白卡节点样式：白底 + 细边框 + 图标 + 标题/副标题
export function NodeCard({
  typeKey,
  color,
  icon,
  title,
  config,
  subtitleHint,
  selected,
  runStatus,
  width = 220,
  onDoubleClick,
  onAddNext,
  actions,
  children,
  dynamicOutputs,
  inputChips,
  flowType,
}: NodeCardProps) {
  // 动态副标题优先，后端 subtitle_hint 仅作静态兜底；
  // 对话流开始节点用「输入」芯片行表达，不兜底显示「工作流入口」
  const dynamicSubtitle = buildNodeSubtitle(typeKey, config, flowType)
  const subtitle = inputChips?.length ? dynamicSubtitle : dynamicSubtitle || subtitleHint || ''
  const [hover, setHover] = useState(false)
  // 菜单展开期间保持触发按钮可见，避免鼠标移入弹出层时按钮闪烁
  const [menuOpen, setMenuOpen] = useState(false)
  const showActions = Boolean(actions?.length) && (hover || menuOpen)

  let borderColor: string = CANVAS_TOKENS.border
  let boxShadow = '0 1px 2px rgba(0,0,0,0.04)'
  if (selected) {
    borderColor = CANVAS_TOKENS.accent
    boxShadow = '0 0 0 2px rgba(99,102,241,0.18), 0 1px 3px rgba(0,0,0,0.06)'
  }
  if (runStatus === 'running') {
    borderColor = CANVAS_TOKENS.running
    boxShadow = '0 0 0 3px rgba(139,92,246,0.25)'
  } else if (runStatus === 'success') {
    borderColor = CANVAS_TOKENS.run
  } else if (runStatus === 'error') {
    borderColor = CANVAS_TOKENS.danger
    boxShadow = '0 0 0 3px rgba(239,68,68,0.15)'
  }

  return (
    <div
      onDoubleClick={onDoubleClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        width,
        padding: '10px 12px',
        background: '#ffffff',
        border: `1px solid ${borderColor}`,
        borderRadius: 8,
        boxShadow,
        cursor: 'grab',
        userSelect: 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        transition: 'border-color 0.15s, box-shadow 0.15s',
        animation:
          runStatus === 'running' ? 'boxia-node-pulse 1.2s ease-in-out infinite' : undefined,
      }}
    >
      {/* hover 时右上角显示「⋯」，聚合重命名 / 复制 / 删除（对齐 Coze 卡片右上角操作） */}
      {showActions && (
        <div
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            top: -10,
            right: -10,
            width: 20,
            height: 20,
            borderRadius: '50%',
            background: CANVAS_TOKENS.white,
            border: `1px solid ${CANVAS_TOKENS.border}`,
            color: '#6b7280',
            fontSize: 14,
            lineHeight: '17px',
            textAlign: 'center',
            cursor: 'pointer',
            boxShadow: '0 2px 4px rgba(0,0,0,0.12)',
            zIndex: 13,
          }}
        >
          <Dropdown
            trigger={['click']}
            open={menuOpen}
            onOpenChange={setMenuOpen}
            placement="bottomRight"
            menu={{
              items: (actions || []).map(({ key, label, danger, disabled }) => ({
                key,
                label,
                danger,
                disabled,
              })),
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation()
                const action = actions?.find((item) => item.key === key)
                setMenuOpen(false)
                action?.onClick()
              },
            }}
          >
            <MoreOutlined />
          </Dropdown>
        </div>
      )}
      {/* V9：hover 时节点右侧显示 + 按钮，点击在节点下方弹出 AddNodePopover（与「⋯」错开） */}
      {onAddNext && hover && (
        <div
          onClick={(e) => {
            e.stopPropagation()
            onAddNext()
          }}
          style={{
            position: 'absolute',
            top: '50%',
            right: -10,
            transform: 'translateY(-50%)',
            width: 20,
            height: 20,
            borderRadius: '50%',
            background: '#4f46e5',
            color: '#fff',
            fontSize: 14,
            lineHeight: '20px',
            textAlign: 'center',
            cursor: 'pointer',
            boxShadow: '0 2px 4px rgba(79,70,229,0.4)',
            zIndex: 12,
          }}
        >
          +
        </div>
      )}
      <NodeIcon typeKey={typeKey} color={color} icon={icon} size={30} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: '#111827',
            lineHeight: '18px',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {title}
        </div>
        {subtitle && (
          <div
            style={{
              fontSize: 11,
              color: '#6b7280',
              lineHeight: '16px',
              marginTop: 2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {subtitle}
          </div>
        )}
        {/* 输入芯片行（对话流开始节点，对齐 Coze：输入 str:USER_INPUT str:CONVERSATION_NAME） */}
        {inputChips && inputChips.length > 0 && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              marginTop: 4,
              flexWrap: 'wrap',
            }}
          >
            <span style={{ fontSize: 11, color: '#9ca3af', flexShrink: 0 }}>输入</span>
            {inputChips.map((chip) => (
              <span
                key={chip.name}
                style={{
                  fontSize: 11,
                  fontFamily: 'monospace',
                  background: '#f3f4f6',
                  color: '#374151',
                  borderRadius: 4,
                  padding: '1px 6px',
                  whiteSpace: 'nowrap',
                }}
              >
                {typeShortLabel(chip.type)}:{chip.name}
              </span>
            ))}
          </div>
        )}
        {/* if_else 动态出口：每行一个 [data-port-id] 元素，FlowGram 会自动在该位置渲染端口圆点
            WorkflowPointStyle 是 position:absolute; left:50%; top:50%; margin:-10px，
            portal 进 targetElement 后以其为 containing block 居中，因此 targetElement 必须
            自身 position:absolute 贴在每行右缘，圆点才会居中到各分支行高度
            视觉参考 coze：浅灰圆角文本块承载条件标签，圆点紧贴文本块右缘 */}
        {dynamicOutputs && dynamicOutputs.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {dynamicOutputs.map((port) => (
              <div
                key={port.portID}
                style={{
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                <div
                  style={{
                    flex: 1,
                    background: '#f3f4f6',
                    borderRadius: 4,
                    padding: '3px 8px',
                    fontSize: 11,
                    color: '#374151',
                    lineHeight: '16px',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {port.label}
                </div>
                <div
                  data-port-id={port.portID}
                  data-port-type="output"
                  style={{
                    position: 'absolute',
                    right: -9,
                    top: 0,
                    bottom: 0,
                    width: 1,
                  }}
                />
              </div>
            ))}
          </div>
        )}
      </div>
      {children}
    </div>
  )
}
