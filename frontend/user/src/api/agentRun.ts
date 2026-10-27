import { request } from './client'

export interface ToolCallTrace {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  observation: string
  is_error: boolean
}

export interface AgentRunResponse {
  agent_id: string
  run_id: string
  conversation_id: string
  content: string
  tool_traces: ToolCallTrace[]
  iterations: number
  usage: Record<string, number>
  finish_reason: string
}

export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export async function runAgent(
  agentId: string,
  body: { query: string; conversation_id?: string; history?: ChatHistoryItem[] },
): Promise<AgentRunResponse> {
  return request<AgentRunResponse>(`/user/agents/${agentId}/run`, {
    method: 'POST',
    body: JSON.stringify({
      query: body.query,
      conversation_id: body.conversation_id ?? '',
      history: body.history ?? [],
    }),
  })
}
