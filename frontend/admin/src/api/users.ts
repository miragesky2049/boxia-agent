import { request } from './client'
import type { AdminUser, AdminUserCreatePayload, AdminUserUpdatePayload, PageResult } from './types'

export interface UserListParams {
  page?: number
  page_size?: number
  keyword?: string
}

export async function listUsers(params: UserListParams = {}): Promise<PageResult<AdminUser>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  return request<PageResult<AdminUser>>(`/admin/users?${query.toString()}`)
}

export async function createUser(payload: AdminUserCreatePayload): Promise<AdminUser> {
  return request<AdminUser>('/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateUser(id: number, payload: AdminUserUpdatePayload): Promise<AdminUser> {
  return request<AdminUser>(`/admin/users/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function resetUserPassword(id: number, newPassword: string): Promise<void> {
  await request<void>(`/admin/users/${id}/password`, {
    method: 'POST',
    body: JSON.stringify({ new_password: newPassword }),
  })
}
