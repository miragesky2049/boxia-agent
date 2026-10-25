import { request } from './client'
import type { PageResult, UserAgentDetail, UserAgentSummary } from './types'

export async function listAgents(
  params: { page?: number; page_size?: number; keyword?: string } = {},
): Promise<PageResult<UserAgentSummary>> {
  const query = new URLSearchParams()
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))
  if (params.keyword) query.set('keyword', params.keyword)
  const suffix = query.size > 0 ? `?${query.toString()}` : ''
  return request<PageResult<UserAgentSummary>>(`/user/agents${suffix}`)
}

export async function getAgent(agentId: number): Promise<UserAgentDetail> {
  return request<UserAgentDetail>(`/user/agents/${agentId}`)
}
