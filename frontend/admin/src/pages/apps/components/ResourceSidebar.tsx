import { Button, Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { LeftOutlined, RightOutlined, MoreOutlined, SwapOutlined } from '@ant-design/icons'
import type { FlowType } from '../../../api/apps'

interface ResourceSidebarProps {
  appName: string
  collapsed: boolean
  flowType: FlowType
  flowTypeSwitching: boolean
  onSwitchFlowType: (next: FlowType) => void
  onToggleCollapse: () => void
  onOpenVariables: () => void
  onOpenVersions: () => void
  onOpenConversation: () => void
}

// 左侧资源树（V4）：对齐 Coze 结构，节点库已迁移到底部 +添加节点气泡
export function ResourceSidebar({
  appName,
  collapsed,
  flowType,
  flowTypeSwitching,
  onSwitchFlowType,
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
          width: 40,
          flexShrink: 0,
          padding: '8px 0',
          background: '#fafafa',
          borderRight: '1px solid #f0f0f0',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <Button type="text" size="small" icon={<RightOutlined />} onClick={onToggleCollapse} />
      </div>
    )
  }

  return (
    <div
      className="boxia-left-panel"
      style={{
        width: 280,
        flexShrink: 0,
        padding: 12,
        background: '#fafafa',
        borderRight: '1px solid #f0f0f0',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        overflowY: 'auto',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 8,
          padding: '0 4px',
        }}
      >
        <span style={{ fontSize: 12, color: '#6b7280', fontWeight: 600 }}>资源</span>
        <Button type="text" size="small" icon={<LeftOutlined />} onClick={onToggleCollapse} />
      </div>

      <div style={{ fontSize: 11, color: '#9ca3af', padding: '4px 4px 2px' }}>
        {flowType === 'agent' ? '智能体' : flowType === 'chatflow' ? '对话流' : '工作流'}
      </div>
      <FlowTypeResourceItem
        appName={appName}
        flowType={flowType}
        switching={flowTypeSwitching}
        onSwitchFlowType={onSwitchFlowType}
      />

      <div style={{ fontSize: 11, color: '#9ca3af', padding: '12px 4px 2px' }}>设置</div>
      <SidebarItem icon="(x)" label="变量" onClick={onOpenVariables} />
      <SidebarItem icon="🕘" label="版本历史" onClick={onOpenVersions} />
      <SidebarItem icon="💬" label="会话管理" onClick={onOpenConversation} />
    </div>
  )
}

// 资源树中的应用条目：hover 出现「...」菜单，形态切换收进菜单里（对齐 Coze），
// 实际切换前由上层弹出二次确认，避免误操作
function FlowTypeResourceItem({
  appName,
  flowType,
  switching,
  onSwitchFlowType,
}: {
  appName: string
  flowType: FlowType
  switching: boolean
  onSwitchFlowType: (next: FlowType) => void
}) {
  const isChatflow = flowType === 'chatflow'
  const isAgent = flowType === 'agent'
  // 0074 PRD U2（M3）：智能体 ↔ 对话流互转放开；切回工作流后端按节点集合校验
  const menuItems: MenuProps['items'] = [
    {
      key: 'hint',
      disabled: true,
      label: <span style={{ fontSize: 12, color: '#9ca3af' }}>切换会改变画布的执行语义</span>,
    },
    { type: 'divider' },
    // 0074 PRD U2：智能体可切对话流/工作流；其余保持原双向切换
    ...(flowType === 'workflow'
      ? [
          {
            key: 'to-chatflow',
            icon: <SwapOutlined />,
            disabled: switching,
            label: '切换为对话流',
            onClick: () => onSwitchFlowType('chatflow' as FlowType),
          },
        ]
      : isChatflow
        ? [
            {
              key: 'to-workflow',
              icon: <SwapOutlined />,
              disabled: switching,
              label: '切换为工作流',
              onClick: () => onSwitchFlowType('workflow' as FlowType),
            },
          ]
        : [
            {
              key: 'to-chatflow',
              icon: <SwapOutlined />,
              disabled: switching,
              label: '切换为对话流',
              onClick: () => onSwitchFlowType('chatflow' as FlowType),
            },
            {
              key: 'to-workflow',
              icon: <SwapOutlined />,
              disabled: switching,
              label: '切换为工作流',
              onClick: () => onSwitchFlowType('workflow' as FlowType),
            },
          ]),
  ]

  const tooltip = isAgent
    ? '智能体：模型自主规划与工具调用，配置面统一维护人设/工具/知识库'
    : isChatflow
      ? '对话流：多轮会话、中间消息输出、支持问答节点'
      : '工作流：单次执行返回结果'
  const emoji = isAgent ? '🤖' : isChatflow ? '💬' : '📄'

  return (
    <div
      className="boxia-flow-type-item"
      style={{
        padding: '8px 12px',
        background: '#eef2ff',
        borderRadius: 6,
        fontSize: 13,
        color: '#4f46e5',
        fontWeight: 500,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <Tooltip title={tooltip}>
        <span style={{ fontSize: 14 }}>{emoji}</span>
      </Tooltip>
      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {appName || '当前工作流'}
      </span>
      <Dropdown menu={{ items: menuItems }} trigger={['click']} placement="bottomRight">
        <Button type="text" size="small" icon={<MoreOutlined />} style={{ opacity: 0.65 }} />
      </Dropdown>
    </div>
  )
}

function SidebarItem({
  icon,
  label,
  onClick,
  disabled,
}: {
  icon: string
  label: string
  onClick: () => void
  disabled?: boolean
}) {
  return (
    <div
      onClick={disabled ? undefined : onClick}
      style={{
        padding: '8px 12px',
        borderRadius: 6,
        fontSize: 13,
        color: disabled ? '#9ca3af' : '#374151',
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        opacity: disabled ? 0.6 : 1,
      }}
      onMouseEnter={(e) => {
        if (!disabled) e.currentTarget.style.background = '#f3f4f6'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'transparent'
      }}
    >
      <span style={{ fontSize: 12, width: 16, textAlign: 'center' }}>{icon}</span>
      <span>{label}</span>
    </div>
  )
}
