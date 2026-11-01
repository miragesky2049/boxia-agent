import { useEffect, useMemo, useRef, useState } from 'react';
import { Input, Empty } from 'antd';
import type { NodeMeta } from '../../../api/nodeMeta';
import { NodeIcon } from './NodeIcon';

// 与后端 node_meta.py 的 category 对齐，按顺序展示分组
const CATEGORY_LABELS: Array<{ key: string; label: string }> = [
  { key: 'control', label: '流程控制' },
  { key: 'ai', label: 'AI 能力' },
  { key: 'logic', label: '逻辑与工具' },
  { key: 'data', label: '数据' },
  { key: 'conversation', label: '会话与消息' },
  { key: 'misc', label: '其他' },
];

interface AddNodePopoverProps {
  x: number;
  y: number;
  metas: NodeMeta[];
  onSelect: (typeKey: string) => void;
  onClose: () => void;
}

// 连线端点弹出节点面板（U-B2）：从端口拖线到空白处时弹出
export function AddNodePopover({ x, y, metas, onSelect, onClose }: AddNodePopoverProps) {
  const [query, setQuery] = useState('');
  const [filtered, setFiltered] = useState<NodeMeta[]>(metas);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!query.trim()) {
      setFiltered(metas);
    } else {
      const q = query.toLowerCase();
      setFiltered(
        metas.filter(
          (m) =>
            m.title.toLowerCase().includes(q) ||
            m.type_key.toLowerCase().includes(q) ||
            (m.description || '').toLowerCase().includes(q),
        ),
      );
    }
  }, [query, metas]);

  const groups = useMemo(() => {
    const visible = filtered.filter((m) => m.type_key !== 'start');
    return CATEGORY_LABELS
      .map(({ key, label }) => ({
        key,
        label,
        items: visible.filter((m) => m.category === key),
      }))
      .filter((g) => g.items.length > 0);
  }, [filtered]);

  useEffect(() => {
    // 延迟绑定：避免触发 popover 的那个 click 事件冒泡到 document 时立即关闭它
    let handler: ((e: MouseEvent) => void) | null = null;
    const timer = setTimeout(() => {
      handler = (e: MouseEvent) => {
        const target = e.target as HTMLElement | null;
        if (target?.closest('[data-add-node-popover]')) return;
        onCloseRef.current();
      };
      document.addEventListener('click', handler);
    }, 0);
    return () => {
      clearTimeout(timer);
      if (handler) document.removeEventListener('click', handler);
    };
  }, []);

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
            <div style={{
              fontSize: 11, fontWeight: 600, color: '#9ca3af',
              padding: '4px 8px', letterSpacing: 0.5,
            }}>
              {group.label}
            </div>
            {group.items.map((m) => (
              <div
                key={m.type_key}
                onClick={() => {
                  onSelect(m.type_key);
                  onClose();
                }}
                style={{
                  padding: '6px 8px',
                  borderRadius: 6,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = '#f3f4f6'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
              >
                <NodeIcon typeKey={m.type_key} color={m.color} size={24} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: '#111827' }}>
                    {m.title}
                  </div>
                  {m.description && (
                    <div style={{
                      fontSize: 11, color: '#9ca3af',
                      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    }}>
                      {m.description}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  );
}
