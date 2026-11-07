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

export interface AgentConfigForm {
  systemPrompt: string
  modleName: string
  maxToolRounds: number
  openingRemarks: string
  suggestedQuestions: string[]
  tools: Array<Record<string, unknown>>
  datasets: AgentDatasetEntry[]
  mcpServers: Array<Record<string, unknown>>
  workflows: Array<Record<string, unknown>>
  memory: { shortTerm: AgentShortTermMemory }
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
