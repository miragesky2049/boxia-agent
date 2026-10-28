import { request } from './client'
import type {
  AdminContext,
  PageResult,
  PublicContext,
  Tenant,
  TenantAgent,
  TenantAgentBatchOpenResult,
  TenantAgentOpenResult,
  TenantCreatePayload,
  TenantUpdatePayload,
} from './types'

export async function fetchPublicContext(): Promise<PublicContext> {
  return request<PublicContext>('/public/context', { skipAuth: true, skipRefresh: true })
}

export async function fetchPublicTenants(): Promise<Tenant[]> {
  return request<Tenant[]>('/public/tenants', { skipAuth: true, skipRefresh: true })
}

export async function fetchAdminContext(): Promise<AdminContext> {
  return request<AdminContext>('/admin/context')
}

export async function listTenants(
  params: {
    page?: number
    page_size?: number
    keyword?: string
  } = {},
): Promise<PageResult<Tenant>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  return request<PageResult<Tenant>>(`/admin/tenants?${query.toString()}`)
}

export async function getTenant(id: string): Promise<Tenant> {
  return request<Tenant>(`/admin/tenants/${id}`)
}

export async function createTenant(payload: TenantCreatePayload): Promise<Tenant> {
  return request<Tenant>('/admin/tenants', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateTenant(id: string, payload: TenantUpdatePayload): Promise<Tenant> {
  return request<Tenant>(`/admin/tenants/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function listTenantAgents(
  tenantId: string,
  params: {
    page?: number
    page_size?: number
    keyword?: string
    is_enabled?: boolean
    opened_only?: boolean
  } = {},
): Promise<PageResult<TenantAgent>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled))
  if (params.opened_only) query.set('opened_only', 'true')
  return request<PageResult<TenantAgent>>(`/admin/tenants/${tenantId}/agents?${query.toString()}`)
}

export async function setTenantAgentOpened(
  tenantId: string,
  agentId: string,
  opened: boolean,
): Promise<TenantAgentOpenResult> {
  return request<TenantAgentOpenResult>(`/admin/tenants/${tenantId}/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify({ opened }),
  })
}

export async function setTenantAgentsOpened(
  tenantId: string,
  agentIds: string[],
  opened: boolean,
): Promise<TenantAgentBatchOpenResult> {
  return request<TenantAgentBatchOpenResult>(`/admin/tenants/${tenantId}/agents/batch`, {
    method: 'POST',
    body: JSON.stringify({ agent_ids: agentIds, opened }),
  })
}
