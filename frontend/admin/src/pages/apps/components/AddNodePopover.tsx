import { useEffect, useState } from 'react';
import { Input, Empty } from 'antd';
import type { NodeMeta } from '../../../api/nodeMeta';

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

  useEffect(() => {
    const onClick = () => onClose();
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, [onClose]);

  return (
    <div
      style={{
        position: 'fixed',
        left: x,
        top: y,
        zIndex: 2000,
        width: 280,
        maxHeight: 400,
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
      {filtered.length === 0 ? (
        <Empty description="无匹配节点" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        filtered
          .filter((m) => m.type_key !== 'start')
          .map((m) => (
            <div
              key={m.type_key}
              onClick={() => {
                onSelect(m.type_key);
                onClose();
              }}
              style={{
                padding: '6px 8px',
                borderRadius: 4,
                cursor: 'pointer',
                fontSize: 13,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = '#f3f4f6'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
            >
              <span
                style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: m.color, flexShrink: 0,
                }}
              />
              <span style={{ fontWeight: 500 }}>{m.title}</span>
              <span style={{ fontSize: 11, color: '#9ca3af', marginLeft: 'auto' }}>
                {m.category}
              </span>
            </div>
          ))
      )}
    </div>
  );
}
