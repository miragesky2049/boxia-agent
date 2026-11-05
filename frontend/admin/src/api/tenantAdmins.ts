import { request } from './client'
import type {
  AdminUser,
  AdminUserCreatePayload,
  AdminUserUpdatePayload,
  PageResult,
} from './types'

export interface TenantAdminListParams {
  page?: number
  page_size?: number
  keyword?: string
}

function buildQuery(params: TenantAdminListParams): string {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  return query.toString()
}

/** 平台管理员跨租户维护租户管理员账号。 */
export const tenantAdminsApi = {
  async list(tenantId: string, params: TenantAdminListParams = {}): Promise<PageResult<AdminUser>> {
    return request<PageResult<AdminUser>>(`/admin/tenants/${tenantId}/admins?${buildQuery(params)}`)
  },
  async create(tenantId: string, payload: AdminUserCreatePayload): Promise<AdminUser> {
    return request<AdminUser>(`/admin/tenants/${tenantId}/admins`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(tenantId: string, userId: string, payload: AdminUserUpdatePayload): Promise<AdminUser> {
    return request<AdminUser>(`/admin/tenants/${tenantId}/admins/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(tenantId: string, userId: string): Promise<void> {
    await request<void>(`/admin/tenants/${tenantId}/admins/${userId}`, { method: 'DELETE' })
  },
  async resetPassword(tenantId: string, userId: string, newPassword: string): Promise<void> {
    await request<void>(`/admin/tenants/${tenantId}/admins/${userId}/password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    })
  },
}
