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
}
