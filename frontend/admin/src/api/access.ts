import { request } from './client'
import type {
  GrantBatchPayload,
  PageResult,
  PermissionResource,
  ResourceGrant,
  ResourceType,
  Role,
  RoleCopyPayload,
  RoleCreatePayload,
  RoleGrantResource,
  RoleGrantSummary,
  RolePermissionList,
  RoleUpdatePayload,
  UserRoleAssignPayload,
} from './types'

export interface RoleListParams {
  tenant_id?: string
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
  async get(id: string, tenantId?: string): Promise<Role> {
    const suffix = tenantId !== undefined ? `?tenant_id=${tenantId}` : ''
    return request<Role>(`/admin/roles/${id}${suffix}`)
  },
  async create(payload: RoleCreatePayload): Promise<Role> {
    return request<Role>('/admin/roles', { method: 'POST', body: JSON.stringify(payload) })
  },
  async copy(id: string, payload: RoleCopyPayload): Promise<Role> {
    return request<Role>(`/admin/roles/${id}/copy`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: RoleUpdatePayload): Promise<Role> {
    return request<Role>(`/admin/roles/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/roles/${id}`, { method: 'DELETE' })
  },
  async permissions(): Promise<PermissionResource[]> {
    return request<PermissionResource[]>('/admin/permissions')
  },
  async listPermissions(id: string): Promise<RolePermissionList> {
    return request<RolePermissionList>(`/admin/roles/${id}/permissions`)
  },
  async replacePermissions(id: string, codes: string[]): Promise<RolePermissionList> {
    return request<RolePermissionList>(`/admin/roles/${id}/permissions`, {
      method: 'PUT',
      body: JSON.stringify({ codes }),
    })
  },
  async addPermissions(id: string, codes: string[]): Promise<RolePermissionList> {
    return request<RolePermissionList>(`/admin/roles/${id}/permissions`, {
      method: 'POST',
      body: JSON.stringify({ codes }),
    })
  },
  async removePermission(id: string, code: string): Promise<void> {
    await request<void>(`/admin/roles/${id}/permissions/${encodeURIComponent(code)}`, {
      method: 'DELETE',
    })
  },
  async grantSummary(id: string): Promise<RoleGrantSummary> {
    return request<RoleGrantSummary>(`/admin/roles/${id}/grants/summary`)
  },
  async listGrants(
    id: string,
    params: RoleGrantListParams,
  ): Promise<PageResult<RoleGrantResource>> {
    const query = new URLSearchParams({
      resource_type: params.resource_type,
      page: String(params.page ?? 1),
      page_size: String(params.page_size ?? 20),
      granted_only: String(params.granted_only ?? false),
    })
    if (params.keyword) query.set('keyword', params.keyword)
    return request<PageResult<RoleGrantResource>>(`/admin/roles/${id}/grants?${query.toString()}`)
  },
  async addGrants(
    id: string,
    resourceType: ResourceType,
    resourceIds: string[],
  ): Promise<{ updated: number }> {
    return request<{ updated: number }>(`/admin/roles/${id}/grants/${resourceType}`, {
      method: 'POST',
      body: JSON.stringify({ resource_ids: resourceIds }),
    })
  },
  async removeGrant(id: string, resourceType: ResourceType, resourceId: string): Promise<void> {
    await request<void>(`/admin/roles/${id}/grants/${resourceType}/${resourceId}`, {
      method: 'DELETE',
    })
  },
  async setTenantWide(id: string, resourceType: ResourceType, resourceId: string): Promise<void> {
    await request<void>(`/admin/roles/${id}/grants/${resourceType}/${resourceId}/tenant-wide`, {
      method: 'PUT',
    })
  },
}

export const grantsApi = {
  async list(
    resourceType: ResourceType,
    resourceId: string,
    tenantId?: string,
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
