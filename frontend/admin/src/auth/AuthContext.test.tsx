import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './AuthContext'
import RequireAuth from './RequireAuth'
import { setRefreshToken } from './tokenStore'

const adminUser = {
  id: 1,
  username: 'admin',
  display_name: '管理员',
  role_id: 1,
  role_code: 'superadmin',
  role_name: '超级管理员',
  tenant_id: null,
  is_platform: true,
  is_active: true,
  must_change_password: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const adminContext = {
  scope: 'platform',
  tenant: null,
  user: adminUser,
  role_code: 'superadmin',
  role_name: '超级管理员',
  permissions: ['agent:read', 'agent:write'],
  menus: ['agents', 'roles', 'users', 'admin-users', 'tenants'],
  app_env: 'local',
  tenant_resolution: 'host',
  tenant_switch_mode: 'none',
  root_domain: 'example.com',
  platform_admin_subdomain: 'admin',
  platform_admin_host: 'admin.example.com',
  platform_name: 'Boxia',
  password_policy: { min_length: 8, max_bytes: 72, min_categories: 2 },
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function Probe() {
  const { user, loading } = useAuth()
  if (loading) return <div>loading</div>
  return <div>{user ? `user:${user.username}` : 'anonymous'}</div>
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AuthProvider', () => {
  it('存在刷新令牌时启动恢复会话', async () => {
    setRefreshToken('bxt_old')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/admin/auth/refresh')) {
        return jsonResponse({
          access_token: 'access-new',
          token_type: 'bearer',
          expires_in: 1800,
          refresh_token: 'bxt_new',
          refresh_expires_in: 1209600,
          user: adminUser,
        })
      }
      if (url.endsWith('/admin/context')) {
        return jsonResponse(adminContext)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('user:admin')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('没有刷新令牌时直接进入未登录状态', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(
      <MemoryRouter>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('anonymous')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

describe('RequireAuth', () => {
  it('未登录访问受保护页面时跳转登录页', async () => {
    vi.stubGlobal('fetch', vi.fn())

    render(
      <MemoryRouter initialEntries={['/apps']}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<div>login-page</div>} />
            <Route
              path="/apps"
              element={
                <RequireAuth>
                  <div>apps-page</div>
                </RequireAuth>
              }
            />
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('login-page')).toBeInTheDocument()
  })
})
