import { DeleteOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Empty, Popconfirm, Spin, Tag } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { clearMemories, deleteMemory, listMemories } from '../../../api/memories'
import type { AgentMemoryItem } from '../../../api/memories'

// M4 PRD F16.6：用户"我的记忆"抽屉——查看/删除/清空本人智能体长期记忆。
const KIND_LABELS: Record<string, string> = {
  preference: '偏好',
  fact: '事实',
  episode: '经历',
}

interface MemoryDrawerProps {
  open: boolean
  applicationId: string
  onClose: () => void
}

export function MemoryDrawer({ open, applicationId, onClose }: MemoryDrawerProps) {
  const [items, setItems] = useState<AgentMemoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await listMemories(applicationId)
      setItems(result.items)
      setTotal(result.total)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '记忆加载失败')
    } finally {
      setLoading(false)
    }
  }, [applicationId])

  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  const removeOne = async (memoryId: string) => {
    try {
      await deleteMemory(applicationId, memoryId)
      void refresh()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '删除失败')
    }
  }

  const clearAll = async () => {
    try {
      await clearMemories(applicationId)
      void refresh()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '清空失败')
    }
  }

  return (
    <Drawer
      title="我的记忆"
      placement="right"
      width={isMobileWidth() ? '86%' : 420}
      open={open}
      onClose={onClose}
      extra={
        <Popconfirm
          title="清空全部记忆？"
          description="删除后智能体不再参考这些内容，且不可恢复。"
          okText="清空"
          cancelText="取消"
          disabled={total === 0}
          onConfirm={() => void clearAll()}
        >
          <Button danger size="small" disabled={total === 0}>
            清空
          </Button>
        </Popconfirm>
      }
    >
      {error && (
        <Alert type="error" message={error} showIcon style={{ marginBottom: 12 }} closable />
      )}
      <p style={{ marginTop: 0, color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
        以下是该智能体从往期对话中沉淀的关于你的记忆（共 {total} 条），删除后不再被参考。
      </p>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : items.length === 0 ? (
        <Empty description="暂无记忆" />
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {items.map((item) => (
            <li
              key={item.memory_id}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'flex-start',
                padding: '10px 0',
                borderBottom: '1px solid rgba(0,0,0,0.06)',
              }}
            >
              <Tag>{KIND_LABELS[item.kind] ?? item.kind}</Tag>
              <span style={{ flex: 1, wordBreak: 'break-word' }}>{item.content}</span>
              <Button
                type="text"
                size="small"
                icon={<DeleteOutlined />}
                aria-label="删除该条记忆"
                onClick={() => void removeOne(item.memory_id)}
              />
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  )
}

function isMobileWidth(): boolean {
  return typeof window !== 'undefined' && window.innerWidth < 768
}
