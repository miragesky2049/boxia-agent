import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  ApartmentOutlined,
  ApiOutlined,
  BranchesOutlined,
  ClusterOutlined,
  CodeOutlined,
  FileSearchOutlined,
  PlayCircleOutlined,
  StopOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import type { ReactElement } from 'react'
import type { V4NodeData, V4NodeType } from '../store/appStore'

const TYPE_META: Record<V4NodeType, { color: string; icon: ReactElement; label: string }> = {
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
  running: '#faad14',
  success: '#52c41a',
  error: '#ff4d4f',
}

interface V4NodeDataWithDebug extends V4NodeData {
  debugStatus?: 'running' | 'success' | 'error'
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

/** 根据节点类型与 config 生成一行简短的配置摘要（用于画布卡片显示） */
function configSummary(nodeData: V4NodeDataWithDebug): string {
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

export function V4CanvasNode({ data, selected }: NodeProps) {
  const nodeData = data as V4NodeDataWithDebug
  const meta = TYPE_META[nodeData.nodeType]
  const hasInput = nodeData.nodeType !== 'start'
  const hasOutput = nodeData.nodeType !== 'end'
  const debugStatus = nodeData.debugStatus
  const borderColor = debugStatus ? DEBUG_BORDER[debugStatus] ?? undefined : undefined
  const border = borderColor ?? (selected ? meta.color : '#d9d9d9')
  const isRunning = debugStatus === 'running'
  const summary = configSummary(nodeData)

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
      }}
    >
      {hasInput && <Handle type="target" position={Position.Left} />}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: meta.color, fontSize: 16 }}>{meta.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, color: '#999' }}>{meta.label}</div>
          <div style={{ fontSize: 13, fontWeight: 500, color: '#262626' }}>
            {nodeData.label}
          </div>
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
      {hasOutput && <Handle type="source" position={Position.Right} />}
    </div>
  )
}
