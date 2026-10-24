import { request } from './client'
import type {
  GrantBatchPayload,
  GrantInput,
  GrantOverviewItem,
  GrantState,
  PageResult,
  ResourceGrant,
  ResourceType,
  Role,
  RoleCreatePayload,
  RoleUpdatePayload,
} from './types'

export interface RoleListParams {
  tenant_id?: number
  include_inactive?: boolean
}

export const rolesApi = {
  async list(params: RoleListParams = {}): Promise<Role[]> {
    const query = new URLSearchParams()
    if (params.tenant_id !== undefined) query.set('tenant_id', String(params.tenant_id))
    if (params.include_inactive) query.set('include_inactive', 'true')
    const suffix = query.toString()
    return request<Role[]>(`/admin/roles${suffix ? `?${suffix}` : ''}`)
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
}

export interface GrantOverviewParams {
  page?: number
  page_size?: number
  keyword?: string
  grant_state?: GrantState
}

export const grantsApi = {
  async overview(
    resourceType: ResourceType,
    params: GrantOverviewParams = {},
  ): Promise<PageResult<GrantOverviewItem>> {
    const query = new URLSearchParams()
    query.set('resource_type', resourceType)
    query.set('page', String(params.page ?? 1))
    query.set('page_size', String(params.page_size ?? 20))
    if (params.keyword) query.set('keyword', params.keyword)
    if (params.grant_state) query.set('grant_state', params.grant_state)
    return request<PageResult<GrantOverviewItem>>(`/admin/grants/overview?${query.toString()}`)
  },
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
  async replace(
    resourceType: ResourceType,
    resourceId: number,
    grants: GrantInput[],
  ): Promise<ResourceGrant[]> {
    return request<ResourceGrant[]>(
      `/admin/grants?resource_type=${resourceType}&resource_id=${resourceId}`,
      { method: 'PUT', body: JSON.stringify({ grants }) },
    )
  },
}
