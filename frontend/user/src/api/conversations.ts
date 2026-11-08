import { request } from './client'

export interface ConversationSummary {
  conversation_id: string
  title: string
  created_at: string | null
  updated_at: string | null
  /** M4 PRD F14.10：接管中透出发言权应用（additive，不在接管中无此两键） */
  active_application_id?: string
  active_application?: string
}

export interface ConversationMessage {
  message_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  tool_calls: Array<{
    id?: string
    name?: string
    arguments?: string
  }>
  created_at: string | null
  /** M4 PRD F14.10：消息归属应用（应答徽标判定 ≠ 会话归属应用） */
  application_id?: string | null
  /** M4 PRD F14.11：system 行仅放行 handoff_notice 通告形态（历史回放气泡） */
  kind?: string
}

export async function listConversations(
  agentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ConversationSummary[]> {
  const query = new URLSearchParams()
  if (params.limit) query.set('limit', String(params.limit))
  if (params.offset) query.set('offset', String(params.offset))
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return request<ConversationSummary[]>(`/user/agents/${agentId}/conversations${suffix}`)
}

export async function listConversationMessages(
  agentId: string,
  conversationId: string,
  limit = 100,
): Promise<ConversationMessage[]> {
  return request<ConversationMessage[]>(
    `/user/agents/${agentId}/conversations/${conversationId}/messages?limit=${limit}`,
  )
}
