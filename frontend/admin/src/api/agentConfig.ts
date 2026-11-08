import { request } from './client'

// 0074 智能体配置面：表单是画布 agent_loop 节点的视图，键名与后端 camelCase 口径一致

export interface AgentDatasetEntry {
  datasetId: string
  name?: string
  description?: string
  mode?: 'onDemand' | 'always'
  topK?: number
  [key: string]: unknown
}

export interface AgentShortTermMemory {
  enabled: boolean
  windowTurns: number
  tokenBudget: number
  strategy: string
}

// M4 PRD F16.1：长期记忆键组（后端恒携带，默认关闭）
export interface AgentLongTermMemory {
  enabled: boolean
  extractModel: string | null
  recallTopK: number
  maxMemories: number
}

// M4-c PRD F14.1：智能体协作挂载项（delegate=工具化委派 / handoff=接管式移交）
export interface AgentSubAgentEntry {
  applicationId: string
  mode?: 'delegate' | 'handoff'
  toolName?: string
  description?: string
  [key: string]: unknown
}

export interface AgentConfigForm {
  systemPrompt: string
  modleName: string
  maxToolRounds: number
  openingRemarks: string
  suggestedQuestions: string[]
  tools: Array<Record<string, unknown>>
  datasets: AgentDatasetEntry[]
  mcpServers: Array<Record<string, unknown>>
  // M4-b F17.4：MCP 会话保持档位（后端恒携带；会话档连接池为 P1，配置键先行）
  mcpSession: { scope: 'run' | 'conversation' }
  workflows: Array<Record<string, unknown>>
  // M4-c F14.1：协作挂载（后端恒携带，默认空列表；缺键会静默丢配置，必须显式声明）
  subAgents: AgentSubAgentEntry[]
  memory: { shortTerm: AgentShortTermMemory; longTerm: AgentLongTermMemory }
  reasoningMode: 'react' | 'planExecuteReflect'
  plannerPrompt?: string | null
  reflectorPrompt?: string | null
  maxReflectRounds?: number | null
  sensitiveTools: Array<Record<string, unknown>>
  // 0074 PRD F9（M3）：视觉开关（前端按所选模型 capabilities.supports_vision 门控）
  visionEnabled: boolean
  tokenBudget?: number | null
}

export function getAgentConfig(applicationId: string): Promise<AgentConfigForm> {
  return request<AgentConfigForm>(`/admin/apps/${applicationId}/agent-config`)
}

export function saveAgentConfig(
  applicationId: string,
  form: AgentConfigForm,
): Promise<AgentConfigForm> {
  return request<AgentConfigForm>(`/admin/apps/${applicationId}/agent-config`, {
    method: 'PUT',
    body: JSON.stringify(form),
  })
}
