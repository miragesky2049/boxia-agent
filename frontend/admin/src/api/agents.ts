import { request } from './client'
import type {
  Agent,
  AgentOpenedTenant,
  AgentPayload,
  AgentSummary,
  ListParams,
  PageResult,
} from './types'

export async function listAgents(params: ListParams): Promise<PageResult<AgentSummary>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled))
  return request<PageResult<AgentSummary>>(`/admin/agents?${query.toString()}`)
}

export async function listAgentTenants(
  agentId: string,
  params: { page?: number; page_size?: number; keyword?: string } = {},
): Promise<PageResult<AgentOpenedTenant>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  return request<PageResult<AgentOpenedTenant>>(
    `/admin/agents/${agentId}/tenants?${query.toString()}`,
  )
}

export async function getAgent(id: string): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}`)
}

export async function createAgent(payload: AgentPayload): Promise<Agent> {
  return request<Agent>('/admin/agents', { method: 'POST', body: JSON.stringify(payload) })
}

export async function updateAgent(id: string, payload: AgentPayload): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteAgent(id: string): Promise<void> {
  await request<void>(`/admin/agents/${id}`, { method: 'DELETE' })
}
