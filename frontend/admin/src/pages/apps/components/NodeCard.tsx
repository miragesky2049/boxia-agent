import { useState } from 'react';
import { NodeIcon } from './NodeIcon';
import { buildNodeSubtitle } from './nodeSubtitle';
import type { RunNodeStatus } from './nodeStatus';

interface NodeCardProps {
  typeKey: string;
  color: string;
  title: string;
  config?: Record<string, any>;
  selected?: boolean;
  runStatus?: RunNodeStatus;
  width?: number;
  onDoubleClick?: () => void;
  onAddNext?: () => void;
  children?: React.ReactNode;
}

// 与 Coze 对齐的白卡节点样式：白底 + 细边框 + 图标 + 标题/副标题
export function NodeCard({
  typeKey,
  color,
  title,
  config,
  selected,
  runStatus,
  width = 220,
  onDoubleClick,
  onAddNext,
  children,
}: NodeCardProps) {
  const subtitle = buildNodeSubtitle(typeKey, config);
  const [hover, setHover] = useState(false);

  let borderColor = '#e5e7eb';
  let boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
  if (selected) {
    borderColor = '#6366f1';
    boxShadow = '0 0 0 2px rgba(99,102,241,0.18), 0 1px 3px rgba(0,0,0,0.06)';
  }
  if (runStatus === 'running') {
    borderColor = '#8b5cf6';
    boxShadow = '0 0 0 3px rgba(139,92,246,0.25)';
  } else if (runStatus === 'success') {
    borderColor = '#10b981';
  } else if (runStatus === 'error') {
    borderColor = '#ef4444';
    boxShadow = '0 0 0 3px rgba(239,68,68,0.15)';
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
        animation: runStatus === 'running' ? 'boxia-node-pulse 1.2s ease-in-out infinite' : undefined,
      }}
    >
      {/* V9：hover 时右上角显示 + 按钮，点击在节点下方弹出 AddNodePopover */}
      {onAddNext && hover && (
        <div
          onClick={(e) => {
            e.stopPropagation();
            onAddNext();
          }}
          style={{
            position: 'absolute', top: -10, right: -10,
            width: 20, height: 20, borderRadius: '50%',
            background: '#4f46e5', color: '#fff',
            fontSize: 14, lineHeight: '20px', textAlign: 'center',
            cursor: 'pointer', boxShadow: '0 2px 4px rgba(79,70,229,0.4)',
            zIndex: 12,
          }}
        >
          +
        </div>
      )}
      <NodeIcon typeKey={typeKey} color={color} size={30} />
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
      </div>
      {children}
    </div>
  );
}
