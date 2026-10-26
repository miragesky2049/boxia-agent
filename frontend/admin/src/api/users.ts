import { request } from './client'
import type {
  AdminUser,
  AdminUserCreatePayload,
  AdminUserUpdatePayload,
  PageResult,
  User,
  UserCreatePayload,
  UserOption,
  UserUpdatePayload,
} from './types'

export interface UserListParams {
  page?: number
  page_size?: number
  keyword?: string
  department_id?: string
}

function buildQuery(params: UserListParams): string {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.department_id) query.set('department_id', params.department_id)
  return query.toString()
}

/** 租户最终用户：由租户超级管理员维护，支持多角色绑定。 */
export const usersApi = {
  async list(params: UserListParams = {}): Promise<PageResult<User>> {
    return request<PageResult<User>>(`/admin/users?${buildQuery(params)}`)
  },
  async options(keyword?: string): Promise<UserOption[]> {
    const query = new URLSearchParams()
    if (keyword) query.set('keyword', keyword)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<UserOption[]>(`/admin/users/options${suffix}`)
  },
  async create(payload: UserCreatePayload): Promise<User> {
    return request<User>('/admin/users', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: UserUpdatePayload): Promise<User> {
    return request<User>(`/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/users/${id}`, { method: 'DELETE' })
  },
  async resetPassword(id: string, newPassword: string): Promise<void> {
    await request<void>(`/admin/users/${id}/password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    })
  },
}

/** 管理员账号：平台作用域为 admin_users，租户作用域为拥有管理角色的用户。 */
export const adminUsersApi = {
  async list(params: UserListParams = {}): Promise<PageResult<AdminUser>> {
    return request<PageResult<AdminUser>>(`/admin/admin-users?${buildQuery(params)}`)
  },
  async create(payload: AdminUserCreatePayload): Promise<AdminUser> {
    return request<AdminUser>('/admin/admin-users', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: AdminUserUpdatePayload): Promise<AdminUser> {
    return request<AdminUser>(`/admin/admin-users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/admin-users/${id}`, { method: 'DELETE' })
  },
  async resetPassword(id: string, newPassword: string): Promise<void> {
    await request<void>(`/admin/admin-users/${id}/password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    })
  },
}
