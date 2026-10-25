import { request } from './client'
import type { LoginResponse, UserProfile } from './types'

export async function login(username: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>('/user/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
    skipAuth: true,
    skipRefresh: true,
  })
}

export async function logout(): Promise<void> {
  await request<void>('/user/auth/logout', { method: 'POST', skipRefresh: true })
}

export async function fetchMe(): Promise<UserProfile> {
  return request<UserProfile>('/user/me')
}
