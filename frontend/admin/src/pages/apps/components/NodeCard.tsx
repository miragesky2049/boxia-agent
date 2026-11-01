import { useState } from 'react';
import { Dropdown } from 'antd';
import { MoreOutlined } from '@ant-design/icons';
import { NodeIcon } from './NodeIcon';
import { buildNodeSubtitle } from './nodeSubtitle';
import type { RunNodeStatus } from './nodeStatus';
import { CANVAS_TOKENS } from '../canvas/tokens';

export interface NodeCardAction {
  key: string;
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}

interface NodeCardProps {
  typeKey: string;
  color: string;
  icon?: string;
  title: string;
  config?: Record<string, any>;
  subtitleHint?: string;
  selected?: boolean;
  runStatus?: RunNodeStatus;
  width?: number;
  onDoubleClick?: () => void;
  onAddNext?: () => void;
  actions?: NodeCardAction[];
  children?: React.ReactNode;
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
}: NodeCardProps) {
  // 动态副标题优先，后端 subtitle_hint 仅作静态兜底
  const subtitle = buildNodeSubtitle(typeKey, config) || subtitleHint || '';
  const [hover, setHover] = useState(false);
  // 菜单展开期间保持触发按钮可见，避免鼠标移入弹出层时按钮闪烁
  const [menuOpen, setMenuOpen] = useState(false);
  const showActions = Boolean(actions?.length) && (hover || menuOpen);

  let borderColor: string = CANVAS_TOKENS.border;
  let boxShadow = '0 1px 2px rgba(0,0,0,0.04)';
  if (selected) {
    borderColor = CANVAS_TOKENS.accent;
    boxShadow = '0 0 0 2px rgba(99,102,241,0.18), 0 1px 3px rgba(0,0,0,0.06)';
  }
  if (runStatus === 'running') {
    borderColor = CANVAS_TOKENS.running;
    boxShadow = '0 0 0 3px rgba(139,92,246,0.25)';
  } else if (runStatus === 'success') {
    borderColor = CANVAS_TOKENS.run;
  } else if (runStatus === 'error') {
    borderColor = CANVAS_TOKENS.danger;
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
      {/* hover 时右上角显示「⋯」，聚合重命名 / 复制 / 删除（对齐 Coze 卡片右上角操作） */}
      {showActions && (
        <div
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute', top: -10, right: -10,
            width: 20, height: 20, borderRadius: '50%',
            background: CANVAS_TOKENS.white, border: `1px solid ${CANVAS_TOKENS.border}`,
            color: '#6b7280', fontSize: 14, lineHeight: '17px', textAlign: 'center',
            cursor: 'pointer', boxShadow: '0 2px 4px rgba(0,0,0,0.12)',
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
                key, label, danger, disabled,
              })),
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation();
                const action = actions?.find((item) => item.key === key);
                setMenuOpen(false);
                action?.onClick();
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
            e.stopPropagation();
            onAddNext();
          }}
          style={{
            position: 'absolute', top: '50%', right: -10,
            transform: 'translateY(-50%)',
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
      </div>
      {children}
    </div>
  );
}
