import type { NodeProps } from '@xyflow/react'
import { Input } from 'antd'
import { useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { useAppStore } from '../store/appStore'

interface StickyData extends Record<string, unknown> {
  nodeType: 'sticky'
  label: string
  config: { content?: string; color?: string; width?: number; height?: number }
}

/** 黄色便签节点：双击编辑文字，右下角可拖拽调整尺寸，无连线端口 */
export function StickyNode({ id, data, selected }: NodeProps) {
  const cfg = (data as StickyData).config ?? {}
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(cfg.content ?? '')
  const updateNodeConfig = useAppStore((s) => s.updateNodeConfig)
  const pushHistory = useAppStore((s) => s.pushHistory)
  const dragRef = useRef<{ startX: number; startY: number; w: number; h: number } | null>(null)

  const color = cfg.color ?? '#fffbe6'
  const border = selected ? '#faad14' : '#ffe58f'
  const width = cfg.width ?? 200
  const height = cfg.height ?? 100

  const commit = () => {
    setEditing(false)
    updateNodeConfig(id, { ...cfg, content: draft })
  }

  const handleResizeStart = (e: MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    pushHistory()
    const startX = e.clientX
    const startY = e.clientY
    dragRef.current = { startX, startY, w: width, h: height }

    const onMove = (ev: globalThis.MouseEvent) => {
      if (!dragRef.current) return
      const dx = ev.clientX - dragRef.current.startX
      const dy = ev.clientY - dragRef.current.startY
      const newW = Math.max(160, dragRef.current.w + dx)
      const newH = Math.max(80, dragRef.current.h + dy)
      updateNodeConfig(id, { ...cfg, width: newW, height: newH })
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const style: CSSProperties = {
    width,
    minHeight: height,
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
    position: 'relative',
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
        style={{ ...style, background: '#fff', fontSize: 12, minHeight: height }}
        autoSize={false}
      />
    )
  }

  return (
    <div style={style} onDoubleClick={() => { setDraft(cfg.content ?? ''); setEditing(true) }} title="双击编辑注释">
      {cfg.content || <span style={{ color: '#bfbfbf' }}>双击添加注释…</span>}
      {/* 右下角 resize 手柄 */}
      <span
        onMouseDown={handleResizeStart}
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute',
          right: 2,
          bottom: 2,
          width: 12,
          height: 12,
          cursor: 'nwse-resize',
          borderRight: '2px solid #d4b106',
          borderBottom: '2px solid #d4b106',
          opacity: selected ? 1 : 0.4,
        }}
        title="拖拽调整尺寸"
      />
    </div>
  )
}
