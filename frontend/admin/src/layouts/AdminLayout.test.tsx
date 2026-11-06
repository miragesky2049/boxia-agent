import { App as AntdApp } from 'antd'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../auth/tokenStore'
import { AuthProvider } from '../auth/AuthContext'
import { TenantProvider } from '../tenant/TenantContext'
import AdminLayout from './AdminLayout'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const passwordPolicy = { min_length: 10, max_bytes: 72, min_categories: 3 }

function mockContext(scope: 'platform' | 'tenant', menus: string[], permissions: string[]) {
  const user = {
    id: '1',
    username: scope === 'platform' ? 'ops' : 'tacme',
    display_name: '管理员',
    role_id: '2',
    role_code: scope === 'platform' ? 'superadmin' : 'admin',
    role_name: '管理员',
    tenant_id: scope === 'platform' ? null : '9',
    is_platform: scope === 'platform',
    is_active: true,
    must_change_password: false,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
  const publicContext = {
    scope,
    tenant:
      scope === 'platform'
        ? null
        : { id: '9', code: 'acme', name: 'Acme', is_active: true, created_at: '', updated_at: '' },
    app_env: 'local',
    tenant_resolution: 'host',
    tenant_switch_mode: 'none',
    root_domain: 'example.com',
    platform_admin_subdomain: 'platform',
    platform_admin_host: 'platform.example.com',
    platform_name: 'Boxia',
    password_policy: passwordPolicy,
  }
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname
    if (pathname.endsWith('/admin/auth/refresh')) {
      return jsonResponse({
        access_token: 'access',
        token_type: 'bearer',
        expires_in: 1800,
        refresh_token: 'bxt_test',
        refresh_expires_in: 1209600,
        user,
      })
    }
    if (pathname.endsWith('/public/context')) return jsonResponse(publicContext)
    if (pathname.endsWith('/admin/context')) {
      return jsonResponse({
        ...publicContext,
        user,
        role_code: user.role_code,
        role_name: user.role_name,
        permissions,
        menus,
      })
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderLayout() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/']}>
        <TenantProvider>
          <AuthProvider>
            <Routes>
              <Route element={<AdminLayout />}>
                <Route path="/" element={<div>内容区</div>} />
              </Route>
            </Routes>
          </AuthProvider>
        </TenantProvider>
      </MemoryRouter>
    </AntdApp>,
  )
}

beforeEach(() => {
  localStorage.clear()
  setRefreshToken('bxt_test')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AdminLayout 双入口菜单', () => {
  it('平台作用域展示开通授权、不展示角色授权', async () => {
    vi.stubGlobal(
      'fetch',
      mockContext('platform', ['entitlements', 'roles'], ['page:entitlements']),
    )
    renderLayout()

    expect(await screen.findByText('开通授权', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText('角色授权')).not.toBeInTheDocument()
  })

  it('角色授权菜单已下线：租户作用域即使旧上下文带 role-access 也不渲染', async () => {
    vi.stubGlobal(
      'fetch',
      mockContext('tenant', ['roles', 'grants', 'role-access'], ['page:roles', 'page:grants']),
    )
    renderLayout()

    expect(await screen.findByText('角色管理', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('用户授权')).toBeInTheDocument()
    expect(screen.queryByText('角色授权')).not.toBeInTheDocument()
    expect(screen.queryByText('开通授权')).not.toBeInTheDocument()
  })
})
