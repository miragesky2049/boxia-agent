import { Button } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';

interface ResourceSidebarProps {
  appName: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onOpenVariables: () => void;
  onOpenVersions: () => void;
  onOpenConversation: () => void;
}

// 左侧资源树（V4）：对齐 Coze 结构，节点库已迁移到底部 +添加节点气泡
export function ResourceSidebar({
  appName,
  collapsed,
  onToggleCollapse,
  onOpenVariables,
  onOpenVersions,
  onOpenConversation,
}: ResourceSidebarProps) {
  if (collapsed) {
    return (
      <div
        className="boxia-left-panel"
        style={{
          width: 40, flexShrink: 0, padding: '8px 0', background: '#fafafa',
          borderRight: '1px solid #f0f0f0',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8,
        }}
      >
        <Button
          type="text"
          size="small"
          icon={<RightOutlined />}
          onClick={onToggleCollapse}
        />
      </div>
    );
  }

  return (
    <div
      className="boxia-left-panel"
      style={{
        width: 280, flexShrink: 0, padding: 12, background: '#fafafa',
        borderRight: '1px solid #f0f0f0',
        display: 'flex', flexDirection: 'column', gap: 4, overflowY: 'auto',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 8, padding: '0 4px',
      }}>
        <span style={{ fontSize: 12, color: '#6b7280', fontWeight: 600 }}>资源</span>
        <Button
          type="text"
          size="small"
          icon={<LeftOutlined />}
          onClick={onToggleCollapse}
        />
      </div>

      <div style={{ fontSize: 11, color: '#9ca3af', padding: '4px 4px 2px' }}>工作流</div>
      <div style={{
        padding: '8px 12px', background: '#eef2ff', borderRadius: 6,
        fontSize: 13, color: '#4f46e5', fontWeight: 500,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span>📄</span>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {appName || '当前工作流'}
        </span>
      </div>

      <div style={{ fontSize: 11, color: '#9ca3af', padding: '12px 4px 2px' }}>设置</div>
      <SidebarItem icon="(x)" label="变量" onClick={onOpenVariables} />
      <SidebarItem icon="🕘" label="版本历史" onClick={onOpenVersions} />
      <SidebarItem icon="💬" label="会话管理（开发中）" onClick={onOpenConversation} disabled />
    </div>
  );
}

function SidebarItem({
  icon, label, onClick, disabled,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <div
      onClick={disabled ? undefined : onClick}
      style={{
        padding: '8px 12px', borderRadius: 6, fontSize: 13,
        color: disabled ? '#9ca3af' : '#374151',
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'flex', alignItems: 'center', gap: 8,
        opacity: disabled ? 0.6 : 1,
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.background = '#f3f4f6';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent';
      }}
    >
      <span style={{ fontSize: 12, width: 16, textAlign: 'center' }}>{icon}</span>
      <span>{label}</span>
    </div>
  );
}
