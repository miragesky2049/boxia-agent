import type { NodeProps } from '@xyflow/react'
import { Input } from 'antd'
import { useState, type CSSProperties } from 'react'
import { useAppStore } from '../store/appStore'

interface StickyData extends Record<string, unknown> {
  nodeType: 'sticky'
  label: string
  config: { content?: string; color?: string }
}

/** 黄色便签节点：双击编辑文字，无连线端口 */
export function StickyNode({ id, data, selected }: NodeProps) {
  const cfg = (data as StickyData).config ?? {}
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(cfg.content ?? '')
  const updateNodeConfig = useAppStore((s) => s.updateNodeConfig)

  const color = cfg.color ?? '#fffbe6'
  const border = selected ? '#faad14' : '#ffe58f'

  const commit = () => {
    setEditing(false)
    updateNodeConfig(id, { ...cfg, content: draft })
  }

  const style: CSSProperties = {
    width: 200,
    minHeight: 100,
    padding: 12,
    background: color,
    border: `2px solid ${border}`,
    borderRadius: 4,
    boxShadow: '0 2px 6px rgba(0,0,0,0.1)',
    fontSize: 12,
    color: '#595959',
    cursor: editing ? 'text' : 'move',
    fontFamily: 'inherit',
    wordBreak: 'break-word',
    whiteSpace: 'pre-wrap',
  }

  if (editing) {
    return (
      <Input.TextArea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault()
            commit()
          }
        }}
        style={{ ...style, background: '#fff', fontSize: 12 }}
        autoSize={{ minRows: 4 }}
      />
    )
  }

  return (
    <div style={style} onDoubleClick={() => { setDraft(cfg.content ?? ''); setEditing(true) }} title="双击编辑注释">
      {cfg.content || <span style={{ color: '#bfbfbf' }}>双击添加注释…</span>}
    </div>
  )
}
