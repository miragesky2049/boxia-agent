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

export interface ToolTrace {
  id: string
  name: string
  status: ToolTraceStatus
  durationMs?: number
  args?: string
  result?: string
  error?: string
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

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  tools?: ToolTrace[]
  error?: MessageError
  question?: QuestionSpec
  notice?: string
  noticeTone?: 'waiting' | 'muted'
}
