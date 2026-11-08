export type AgentStatus = 'online' | 'thinking'

export interface ChatAgent {
  id: string
  name: string
  avatarText: string
}

export interface ConversationItem {
  id: string
  title: string
  updatedAt: string
  /** M4 PRD F14.10：接管中会话的应答专家名（侧栏接管标记） */
  handoffAgent?: string
}

/** M4 PRD F14.10：会话当前发言权（非空=接管中，后续轮次由该专家应答） */
export interface ActiveHandoff {
  applicationId: string
  displayName: string
}

export type ToolTraceStatus = 'running' | 'done' | 'error'

// 0074 PRD F5.3：知识库检索命中来源（SSE tool_end.chunks 映射后的展示形态）
export interface SourceChunk {
  datasetName: string
  chunkId: string
  score?: number
  excerpt?: string
}

export interface ToolTrace {
  id: string
  name: string
  status: ToolTraceStatus
  durationMs?: number
  args?: string
  result?: string
  error?: string
  chunks?: SourceChunk[]
}

// 0074 PRD F4：深度模式阶段进展（plan 任务清单 + 每轮 reflect 结论）
export interface PlanTask {
  id?: string
  goal: string
  acceptance?: string
}

export interface ReflectNote {
  round: number
  done: boolean
  critique?: string
  suggestion?: string
}

export interface QuestionSpec {
  text: string
  options?: string[]
  submitted?: boolean
}

export interface MessageError {
  message: string
  detail?: string
}

export interface PendingQuestion {
  text: string
  options: string[]
  threadId: string
  runId: string
}

// 0074 PRD F10：待审批的工具调用（interrupted 帧 approval 映射后的展示形态）
export interface PendingToolCall {
  id: string
  name: string
  arguments?: string
}

/** F10 审批卡：threadId/runId 供续跑定位挂起 run，submitted 记录已裁决状态 */
export interface ApprovalSpec {
  calls: PendingToolCall[]
  threadId: string
  runId: string
  submitted?: 'approved' | 'rejected'
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  tools?: ToolTrace[]
  error?: MessageError
  question?: QuestionSpec
  /** 0074 PRD F10：敏感工具审批卡（挂起轮产出） */
  approval?: ApprovalSpec
  notice?: string
  noticeTone?: 'waiting' | 'muted'
  /** 0074 PRD F4：深度模式的计划任务清单（plan 帧） */
  plan?: PlanTask[]
  /** 0074 PRD F4：反思轮次结论（reflect 帧，按轮累积） */
  reflects?: ReflectNote[]
  /** M4 PRD F14.10：发言权移交通告（handoff 帧/历史通告行渲染，非真实应答） */
  handoffNotice?: string
  /** M4 PRD F14.10：接管轮应答专家名（消息 application_id≠会话归属应用时展示徽标） */
  answeredBy?: string
}
