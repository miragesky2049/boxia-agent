import { request } from './client'
import type {
  AdminContext,
  PageResult,
  PublicContext,
  Tenant,
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
