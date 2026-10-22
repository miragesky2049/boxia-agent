import { request } from './client'
import type { AdminUser, LoginResponse } from './types'

export async function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/admin/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
    skipAuth: true,
    skipRefresh: true,
  })
}

export async function logout(): Promise<void> {
  await request<void>('/admin/auth/logout', {
    method: 'POST',
    skipRefresh: true,
    skipRetry: true,
  })
}

export async function fetchCurrentUser(): Promise<AdminUser> {
  return request<AdminUser>('/admin/auth/me')
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await request<void>('/admin/auth/password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    skipRefresh: true,
  })
}
