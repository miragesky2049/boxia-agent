import { useEffect, useMemo, useRef, useState } from 'react'
import { Input, Empty, Tooltip } from 'antd'
import type { NodeMeta } from '../../../api/nodeMeta'
import { NodeIcon } from './NodeIcon'
import { buildCategoryGroups } from '../canvas/metadata/nodePresentation'

interface AddNodePopoverProps {
  x: number
  y: number
  metas: NodeMeta[]
  // 这些 type_key 不在面板中展示（如 start 永远隐藏；end 在画布已有 end 时隐藏）
  forbiddenTypeKeys?: Set<string>
  onSelect: (typeKey: string) => void
  onClose: () => void
}

// 连线端点弹出节点面板（U-B2）：从端口拖线到空白处时弹出
export function AddNodePopover({
  x,
  y,
  metas,
  forbiddenTypeKeys,
  onSelect,
  onClose,
}: AddNodePopoverProps) {
  const [query, setQuery] = useState('')
  const [filtered, setFiltered] = useState<NodeMeta[]>(metas)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!query.trim()) {
      setFiltered(metas)
    } else {
      const q = query.toLowerCase()
      setFiltered(
        metas.filter(
          (m) =>
            m.title.toLowerCase().includes(q) ||
            m.type_key.toLowerCase().includes(q) ||
            (m.description || '').toLowerCase().includes(q),
        ),
      )
    }
  }, [query, metas])

  const groups = useMemo(
    () => buildCategoryGroups(filtered, (m) => !forbiddenTypeKeys?.has(m.type_key)),
    [filtered, forbiddenTypeKeys],
  )

  useEffect(() => {
    // 延迟绑定：避免触发 popover 的那个 click 事件冒泡到 document 时立即关闭它
    let handler: ((e: MouseEvent) => void) | null = null
    const timer = setTimeout(() => {
      handler = (e: MouseEvent) => {
        const target = e.target as HTMLElement | null
        if (target?.closest('[data-add-node-popover]')) return
        onCloseRef.current()
      }
      document.addEventListener('click', handler)
    }, 0)
    return () => {
      clearTimeout(timer)
      if (handler) document.removeEventListener('click', handler)
    }
  }, [])

  return (
    <div
      data-add-node-popover
      style={{
        position: 'fixed',
        left: x,
        top: y,
        zIndex: 2000,
        width: 320,
        maxHeight: 460,
        overflowY: 'auto',
        background: '#fff',
        borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        border: '1px solid #e5e7eb',
        padding: 12,
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <Input
        placeholder="搜索节点..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        size="small"
        style={{ marginBottom: 8 }}
        autoFocus
      />
      {groups.length === 0 ? (
        <Empty description="无匹配节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        groups.map((group) => (
          <div key={group.key} style={{ marginBottom: 8 }}>
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: '#9ca3af',
                padding: '4px 8px',
                letterSpacing: 0.5,
              }}
            >
              {group.label}
            </div>
            {group.items.map((m) => {
              const disabled = m.available === false
              return (
                <Tooltip
                  key={m.type_key}
                  title={disabled ? m.unavailable_reason : undefined}
                  placement="right"
                >
                  <div
                    onClick={() => {
                      if (disabled) return
                      onSelect(m.type_key)
                      onClose()
                    }}
                    style={{
                      padding: '6px 8px',
                      borderRadius: 6,
                      cursor: disabled ? 'not-allowed' : 'pointer',
                      opacity: disabled ? 0.45 : 1,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                    onMouseEnter={(e) => {
                      if (!disabled) e.currentTarget.style.background = '#f3f4f6'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    <NodeIcon typeKey={m.type_key} color={m.color} icon={m.icon} size={24} />
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 500, color: '#111827' }}>
                        {m.title}
                        {disabled && (
                          <span style={{ fontSize: 10, color: '#9ca3af', marginLeft: 6 }}>
                            未启用
                          </span>
                        )}
                      </div>
                      {m.description && (
                        <div
                          style={{
                            fontSize: 11,
                            color: '#9ca3af',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                        >
                          {m.description}
                        </div>
                      )}
                    </div>
                  </div>
                </Tooltip>
              )
            })}
          </div>
        ))
      )}
    </div>
  )
}
