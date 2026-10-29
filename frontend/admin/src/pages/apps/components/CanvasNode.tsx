import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  ApartmentOutlined,
  ApiOutlined,
  BranchesOutlined,
  ClusterOutlined,
  CodeOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  FileSearchOutlined,
  MoreOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  StopOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { App, Dropdown, Input, Tooltip } from 'antd'
import { useState, type ReactElement } from 'react'
import type { NodeData, NodeType } from '../store/appStore'
import { listOutputFields, useAppStore } from '../store/appStore'
import { INSERTABLE_TYPES } from './NodeTypes'

const TYPE_META: Record<NodeType, { color: string; icon: ReactElement; label: string }> = {
  start: { color: '#52c41a', icon: <PlayCircleOutlined />, label: '开始' },
  llm: { color: '#1677ff', icon: <ApartmentOutlined />, label: 'LLM' },
  end: { color: '#722ed1', icon: <StopOutlined />, label: '结束' },
  branch: { color: '#faad14', icon: <BranchesOutlined />, label: '条件分支' },
  tool: { color: '#fa8c16', icon: <ToolOutlined />, label: '工具' },
  template: { color: '#13c2c2', icon: <CodeOutlined />, label: '模板' },
  http: { color: '#eb2f96', icon: <ApiOutlined />, label: 'HTTP' },
  retrieval: { color: '#2f54eb', icon: <FileSearchOutlined />, label: '检索' },
  human_task: { color: '#fa541c', icon: <UserOutlined />, label: '人审' },
  subgraph: { color: '#08979c', icon: <ClusterOutlined />, label: '子图' },
}

const DEBUG_BORDER: Record<string, string> = {
  pending: '#d9d9d9',
  running: '#faad14',
  success: '#52c41a',
  error: '#ff4d4f',
}

interface NodeDataWithDebug extends NodeData {
  debugStatus?: 'pending' | 'running' | 'success' | 'error'
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

/** 根据节点类型与 config 生成一行简短的配置摘要（用于画布卡片显示） */
function configSummary(nodeData: NodeDataWithDebug): string {
  const cfg = nodeData.config ?? {}
  switch (nodeData.nodeType) {
    case 'start': {
      const inputs = (cfg.inputs ?? []) as Array<{ name: string }>
      return inputs.length > 0 ? `入参：${inputs.map((i) => i.name).join(', ')}` : '无入参'
    }
    case 'end': {
      const outputs = (cfg.outputs ?? []) as Array<{ name: string }>
      return outputs.length > 0 ? `出参：${outputs.map((o) => o.name).join(', ')}` : '自动汇聚 LLM 输出'
    }
    case 'llm': {
      const model = (cfg.model_id as string) || '未选模型'
      return truncate(model, 24)
    }
    case 'branch': {
      const conditions = (cfg.conditions ?? []) as unknown[]
      return conditions.length > 0 ? `${conditions.length} 条条件` : '未配置条件'
    }
    case 'tool': {
      const rid = (cfg.resource_id as string) || '未绑定工具'
      return truncate(rid, 24)
    }
    case 'template': {
      const tpl = (cfg.template as string) || ''
      return tpl ? truncate(tpl.replace(/\s+/g, ' '), 28) : '空模板'
    }
    case 'http': {
      const method = (cfg.method as string) || 'GET'
      const url = (cfg.url as string) || ''
      return url ? truncate(`${method} ${url}`, 28) : '未配置 URL'
    }
    case 'retrieval': {
      const kb = (cfg.knowledge_base_id as string) || ''
      const topK = Number(cfg.top_k ?? 5)
      return kb ? `kb=${truncate(kb, 20)} top=${topK}` : `未绑定知识库 top=${topK}`
    }
    case 'human_task': {
      const role = (cfg.assignee_role as string) || 'reviewer'
      return `审批：${role}`
    }
    case 'subgraph': {
      const appId = (cfg.application_id as string) || ''
      return appId ? `→ ${truncate(appId, 24)}` : '未选择子图应用'
    }
  }
}

export function CanvasNode({ id, data, selected }: NodeProps) {
  const { message, modal } = App.useApp()
  const nodeData = data as NodeDataWithDebug
  const meta = TYPE_META[nodeData.nodeType]
  const hasInput = nodeData.nodeType !== 'start'
  const hasOutput = nodeData.nodeType !== 'end'
  const debugStatus = nodeData.debugStatus
  const borderColor = debugStatus ? DEBUG_BORDER[debugStatus] ?? undefined : undefined
  const border = borderColor ?? (selected ? meta.color : '#d9d9d9')
  const isRunning = debugStatus === 'running'
  const summary = configSummary(nodeData)

  const removeNode = useAppStore((s) => s.removeNode)
  const duplicateNode = useAppStore((s) => s.duplicateNode)
  const renameNode = useAppStore((s) => s.renameNode)
  const addNodeAfter = useAppStore((s) => s.addNodeAfter)
  const triggerRunStep = useAppStore((s) => s.triggerRunStep)

  const [hover, setHover] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(nodeData.label)

  const isEndpoint = nodeData.nodeType === 'start' || nodeData.nodeType === 'end'

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation()
    modal.confirm({
      title: '删除节点？',
      content: `将删除节点「${nodeData.label}」及其连线`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => removeNode(id),
    })
  }

  const handleDuplicate = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (isEndpoint) {
      message.warning('开始/结束节点不能复制')
      return
    }
    duplicateNode(id)
  }

  const startRename = (e: React.MouseEvent) => {
    e.stopPropagation()
    setDraft(nodeData.label)
    setEditing(true)
  }

  const commitRename = () => {
    const next = draft.trim()
    if (next && next !== nodeData.label) {
      renameNode(id, next)
    }
    setEditing(false)
  }

  const handleRunStep = (e: React.MouseEvent) => {
    e.stopPropagation()
    triggerRunStep(id)
  }

  const handleAddDownstream = (type: NodeType) => {
    const err = addNodeAfter(id, type)
    if (err) {
      message.warning(err)
      return
    }
    message.success(`已在下游添加「${INSERTABLE_TYPES.find((t) => t.type === type)?.label ?? type}」节点`)
  }

  const toolBtn: React.CSSProperties = {
    width: 22,
    height: 22,
    borderRadius: 4,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 12,
    color: '#595959',
    background: '#fff',
    border: '1px solid #e8e8e8',
    cursor: 'pointer',
  }

  return (
    <div
      style={{
        minWidth: 160,
        maxWidth: 220,
        padding: '10px 14px',
        borderRadius: 8,
        background: '#fff',
        border: `2px solid ${border}`,
        boxShadow: isRunning
          ? '0 0 0 4px rgba(250, 173, 20, 0.25)'
          : selected
            ? `0 0 0 3px ${meta.color}33`
            : '0 1px 4px rgba(0,0,0,0.08)',
        position: 'relative',
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {hasInput && (
        <Tooltip title="接收上游节点输出" placement="left">
          <Handle type="target" position={Position.Left} style={{ width: 10, height: 10, background: '#fff', border: '2px solid ' + meta.color }} />
        </Tooltip>
      )}

      {/* 悬浮时顶部工具条：运行此步骤 + 更多菜单 */}
      {hover && !isRunning && (
        <div
          style={{
            position: 'absolute',
            top: -32,
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            gap: 4,
            padding: 2,
            background: '#fff',
            borderRadius: 6,
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            border: '1px solid #f0f0f0',
            zIndex: 10,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <Tooltip title="从该节点试运行">
            <span style={{ ...toolBtn, color: '#52c41a' }} onClick={handleRunStep}>
              <PlayCircleOutlined />
            </span>
          </Tooltip>
          <Dropdown
            trigger={['click']}
            placement="bottomCenter"
            menu={{
              items: [
                { key: 'rename', icon: <EditOutlined />, label: '重命名' },
                { key: 'duplicate', icon: <CopyOutlined />, label: '复制节点', disabled: isEndpoint },
                { type: 'divider' },
                { key: 'delete', icon: <DeleteOutlined />, label: '删除', danger: true },
              ],
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation()
                if (key === 'rename') startRename(domEvent)
                else if (key === 'duplicate') handleDuplicate(domEvent)
                else if (key === 'delete') handleDelete(domEvent)
              },
            }}
          >
            <span style={toolBtn} onClick={(e) => e.stopPropagation()} title="更多操作">
              <MoreOutlined />
            </span>
          </Dropdown>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: meta.color, fontSize: 16 }}>{meta.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: '#999' }}>{meta.label}</div>
          {editing ? (
            <Input
              autoFocus
              size="small"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onPressEnter={commitRename}
              onBlur={commitRename}
              onClick={(e) => e.stopPropagation()}
              style={{ fontSize: 13, height: 22, padding: '0 6px' }}
              maxLength={20}
            />
          ) : (
            <div
              style={{ fontSize: 13, fontWeight: 500, color: '#262626', cursor: 'text' }}
              onDoubleClick={(e) => {
                e.stopPropagation()
                setDraft(nodeData.label)
                setEditing(true)
              }}
              title="双击重命名"
            >
              {nodeData.label}
            </div>
          )}
          <div
            style={{
              fontSize: 11,
              color: '#8c8c8c',
              marginTop: 2,
              fontFamily: 'monospace',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
            title={summary}
          >
            {summary}
          </div>
        </div>
        {isRunning && (
          <span style={{ fontSize: 11, color: '#faad14' }}>运行中</span>
        )}
      </div>

      {hasOutput && (
        <>
          <Tooltip
            title={`输出字段：${listOutputFields(nodeData.nodeType).join('、')}`}
            placement="right"
          >
            <Handle type="source" position={Position.Right} style={{ width: 10, height: 10, background: '#fff', border: '2px solid ' + meta.color }} />
          </Tooltip>
          {/* 输出端口旁「+ 添加节点」 */}
          <Dropdown
            trigger={['click']}
            placement="rightTop"
            disabled={isRunning}
            menu={{
              items: INSERTABLE_TYPES.map((t) => ({ key: t.type, label: t.label })),
              onClick: ({ key, domEvent }) => {
                domEvent.stopPropagation()
                handleAddDownstream(key as NodeType)
              },
            }}
          >
            <Tooltip title="在该节点后添加节点" placement="right">
              <span
                style={{
                  position: 'absolute',
                  right: -14,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  background: '#fff',
                  border: '1px solid #1677ff',
                  color: '#1677ff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  fontSize: 10,
                  opacity: hover ? 1 : 0,
                  transition: 'opacity 0.15s',
                  zIndex: 11,
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <PlusOutlined />
              </span>
            </Tooltip>
          </Dropdown>
        </>
      )}
    </div>
  )
}
