import { useEffect, useState, useCallback } from 'react'

interface MenuItem {
  label: string
  action: () => void
  danger?: boolean
  divider?: boolean
}

interface CanvasContextMenuProps {
  onAddNode: () => void
  onAutoLayout: () => void
  onFitView: () => void
  onDeleteSelected: () => void
  onCopyNode: () => void
  onPasteNode: () => void
  // 右键命中连线时返回 lineId，用于菜单展示「删除连线」
  getLineIdAt?: (e: MouseEvent) => string | null
  onDeleteLine?: (lineId: string) => void
}

// 画布右键菜单（U-P2）：在画布空白处右键弹出
export function CanvasContextMenu({
  onAddNode,
  onAutoLayout,
  onFitView,
  onDeleteSelected,
  onCopyNode,
  onPasteNode,
  getLineIdAt,
  onDeleteLine,
}: CanvasContextMenuProps) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const [lineId, setLineId] = useState<string | null>(null)

  const handleContextMenu = useCallback(
    (e: MouseEvent) => {
      // 只在画布区域触发（不在节点/抽屉上）
      const target = e.target as HTMLElement
      if (
        target.closest('.gedit-flow-activity-node') ||
        target.closest('.ant-drawer') ||
        target.closest('.ant-modal')
      ) {
        return
      }
      e.preventDefault()
      setLineId(getLineIdAt?.(e) ?? null)
      setPos({ x: e.clientX, y: e.clientY })
    },
    [getLineIdAt],
  )

  const close = useCallback(() => {
    setPos(null)
    setLineId(null)
  }, [])

  useEffect(() => {
    const container = document.querySelector<HTMLElement>('.gedit-playground-container')
    if (!container) return
    container.addEventListener('contextmenu', handleContextMenu)
    const onClick = () => close()
    document.addEventListener('click', onClick)
    return () => {
      container.removeEventListener('contextmenu', handleContextMenu)
      document.removeEventListener('click', onClick)
    }
  }, [handleContextMenu, close])

  if (!pos) return null

  const items: MenuItem[] = lineId
    ? [{ label: '删除连线', action: () => onDeleteLine?.(lineId), danger: true }]
    : [
        { label: '添加节点', action: onAddNode },
        { label: '复制节点', action: onCopyNode },
        { label: '粘贴节点', action: onPasteNode },
        { label: '删除选中节点', action: onDeleteSelected, danger: true, divider: true },
        { label: '自动排版', action: onAutoLayout },
        { label: '适应视图', action: onFitView },
      ]

  return (
    <div
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        zIndex: 2000,
        background: '#fff',
        borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
        border: '1px solid #e5e7eb',
        padding: 4,
        minWidth: 140,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {items.map((item, idx) => (
        <div key={idx}>
          {item.divider && <div style={{ height: 1, background: '#f0f0f0', margin: '4px 0' }} />}
          <div
            onClick={() => {
              item.action()
              close()
            }}
            style={{
              padding: '6px 12px',
              fontSize: 13,
              cursor: 'pointer',
              borderRadius: 4,
              color: item.danger ? '#ef4444' : '#374151',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = '#f3f4f6'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'transparent'
            }}
          >
            {item.label}
          </div>
        </div>
      ))}
    </div>
  )
}
