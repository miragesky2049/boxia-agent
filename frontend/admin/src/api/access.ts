import { request } from './client'
import type {
  GrantBatchPayload,
  PageResult,
  ResourceGrant,
  ResourceType,
  Role,
  RoleCreatePayload,
  RoleGrantResource,
  RoleGrantSummary,
  RoleUpdatePayload,
  UserRoleAssignPayload,
} from './types'

export interface RoleListParams {
  tenant_id?: number
  include_inactive?: boolean
}

export interface RoleGrantListParams {
  resource_type: ResourceType
  page?: number
  page_size?: number
  keyword?: string
  granted_only?: boolean
}

export const rolesApi = {
  async list(params: RoleListParams = {}): Promise<Role[]> {
    const query = new URLSearchParams()
    if (params.tenant_id !== undefined) query.set('tenant_id', String(params.tenant_id))
    if (params.include_inactive) query.set('include_inactive', 'true')
    const suffix = query.toString()
    return request<Role[]>(`/admin/roles${suffix ? `?${suffix}` : ''}`)
  },
  async get(id: number, tenantId?: number): Promise<Role> {
    const suffix = tenantId !== undefined ? `?tenant_id=${tenantId}` : ''
    return request<Role>(`/admin/roles/${id}${suffix}`)
  },
  async create(payload: RoleCreatePayload): Promise<Role> {
    return request<Role>('/admin/roles', { method: 'POST', body: JSON.stringify(payload) })
  },
  async update(id: number, payload: RoleUpdatePayload): Promise<Role> {
    return request<Role>(`/admin/roles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: number): Promise<void> {
    await request<void>(`/admin/roles/${id}`, { method: 'DELETE' })
  },
  async grantSummary(id: number): Promise<RoleGrantSummary> {
    return request<RoleGrantSummary>(`/admin/roles/${id}/grants/summary`)
  },
  async listGrants(
    id: number,
    params: RoleGrantListParams,
  ): Promise<PageResult<RoleGrantResource>> {
    const query = new URLSearchParams({
      resource_type: params.resource_type,
      page: String(params.page ?? 1),
      page_size: String(params.page_size ?? 20),
      granted_only: String(params.granted_only ?? false),
    })
    if (params.keyword) query.set('keyword', params.keyword)
    return request<PageResult<RoleGrantResource>>(
      `/admin/roles/${id}/grants?${query.toString()}`,
    )
  },
  async addGrants(
    id: number,
    resourceType: ResourceType,
    resourceIds: number[],
  ): Promise<{ updated: number }> {
    return request<{ updated: number }>(`/admin/roles/${id}/grants/${resourceType}`, {
      method: 'POST',
      body: JSON.stringify({ resource_ids: resourceIds }),
    })
  },
  async removeGrant(
    id: number,
    resourceType: ResourceType,
    resourceId: number,
  ): Promise<void> {
    await request<void>(`/admin/roles/${id}/grants/${resourceType}/${resourceId}`, {
      method: 'DELETE',
    })
  },
}

export const grantsApi = {
  async list(
    resourceType: ResourceType,
    resourceId: number,
    tenantId?: number,
  ): Promise<ResourceGrant[]> {
    const query = new URLSearchParams({
      resource_type: resourceType,
      resource_id: String(resourceId),
    })
    if (tenantId !== undefined) query.set('tenant_id', String(tenantId))
    return request<ResourceGrant[]>(`/admin/grants?${query.toString()}`)
  },
  async batch(payload: GrantBatchPayload): Promise<{ updated: number }> {
    return request<{ updated: number }>('/admin/grants/batch', {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
  async assignUserRoles(payload: UserRoleAssignPayload): Promise<{ updated: number }> {
    return request<{ updated: number }>('/admin/grants/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
}
