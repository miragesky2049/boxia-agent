import { Button } from 'antd'
import type { ButtonProps } from 'antd'
import type { ActionBarAction, ActionBarActionType, ActionBarProps } from './types'
import './boxiaclaw-cmp.css'

/**
 * antd Button 无 secondary 类型，secondary 用 default + 主色描边近似。
 */
function mapButtonType(type: ActionBarActionType | undefined): ButtonProps['type'] {
  switch (type) {
    case 'primary':
      return 'primary'
    case 'secondary':
      return 'default'
    case 'text':
      return 'text'
    case 'default':
    default:
      return 'default'
  }
}

function handleDefaultAction(action: ActionBarAction): void {
  const type = action.action?.type
  if (type === 'goto_free_detail') {
    const sceneRobotId = action.action?.sceneRobotId
    const path =
      typeof sceneRobotId === 'string' && sceneRobotId
        ? `/scene-robots/${encodeURIComponent(sceneRobotId)}`
        : '/scene-robots'
    window.location.assign(path)
  }
}

export default function ActionBar(props: ActionBarProps) {
  const { placement = 'left', actions, onAction, style, className } = props

  const handleClick = (action: ActionBarAction, index: number) => {
    if (action.disabled) return
    if (onAction) {
      onAction(action, index)
      return
    }
    handleDefaultAction(action)
  }

  return (
    <div className={`ab-row ab-row--${placement} ${className ?? ''}`} style={style}>
      {actions.map((action, idx) => {
        const btnType = mapButtonType(action.type)
        const isSecondary = action.type === 'secondary'
        return (
          <Button
            key={`${action.label}-${idx}`}
            type={btnType}
            disabled={action.disabled}
            onClick={() => handleClick(action, idx)}
            style={
              isSecondary
                ? { borderColor: '#2f6bff', color: '#2f6bff', fontWeight: 500 }
                : undefined
            }
          >
            {action.label}
          </Button>
        )
      })}
    </div>
  )
}
