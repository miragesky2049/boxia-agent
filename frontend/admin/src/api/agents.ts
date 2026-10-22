import { request } from './client'
import type { Agent, AgentPayload, AgentSummary, ListParams, PageResult } from './types'

export async function listAgents(params: ListParams): Promise<PageResult<AgentSummary>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled))
  return request<PageResult<AgentSummary>>(`/admin/agents?${query.toString()}`)
}

export async function getAgent(id: number): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}`)
}

export async function createAgent(payload: AgentPayload): Promise<Agent> {
  return request<Agent>('/admin/agents', { method: 'POST', body: JSON.stringify(payload) })
}

export async function updateAgent(id: number, payload: AgentPayload): Promise<Agent> {
  return request<Agent>(`/admin/agents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteAgent(id: number): Promise<void> {
  await request<void>(`/admin/agents/${id}`, { method: 'DELETE' })
}
