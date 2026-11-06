import { App as AntdApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import { TenantProvider } from '../../tenant/TenantContext'
import TenantAppAdminListPage from './TenantAppAdminListPage'

const tenantUser = {
  id: '9',
  username: 'tanops',
  display_name: '租户运营',
  role_id: '2',
  role_code: 'tenant_admin',
  role_name: '租户管理员',
  tenant_id: 't1',
  is_platform: false,
  is_active: true,
  must_change_password: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

interface SubscribedAppRow {
  id: string
  name: string
  avatar_url: string
  description: string
  visibility_lock: boolean
  visibility_template: 'all' | 'whitelist'
  admin_scope_mode?: string
  manageable?: boolean
  configured: boolean
  visibility: 'all' | 'whitelist'
  whitelist_count: number
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(apps: SubscribedAppRow[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const pathname = new URL(String(input), 'http://localhost').pathname
    if (pathname.endsWith('/admin/auth/refresh')) {
      return jsonResponse({
        access_token: 'access',
        token_type: 'bearer',
        expires_in: 1800,
        refresh_token: 'bxt_test',
        refresh_expires_in: 1209600,
        user: tenantUser,
      })
    }
    if (pathname.endsWith('/public/context')) {
      return jsonResponse({
        scope: 'tenant',
        tenant: { id: 't1', code: 'acme', name: 'Acme' },
        app_env: 'local',
        tenant_resolution: 'host',
        tenant_switch_mode: 'none',
        root_domain: 'example.com',
        platform_admin_subdomain: 'platform',
        platform_admin_host: 'platform.example.com',
        platform_name: 'Boxia',
        password_policy: { min_length: 10, max_bytes: 72, min_categories: 3 },
      })
    }
    if (pathname.endsWith('/public/tenants')) return jsonResponse([])
    if (pathname.endsWith('/admin/context')) {
      return jsonResponse({
        user: tenantUser,
        role_code: 'tenant_admin',
        role_name: '租户管理员',
        permissions: ['page:tenant-apps', 'app:admin'],
        menus: ['tenant-apps'],
      })
    }
    if (pathname.endsWith('/admin/tenant/apps')) {
      return jsonResponse(apps)
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/apps']}>
        <TenantProvider>
          <AuthProvider>
            <Routes>
              <Route path="/apps" element={<TenantAppAdminListPage />} />
              <Route path="/tenant-apps/:appId" element={<div>detail-marker</div>} />
            </Routes>
          </AuthProvider>
        </TenantProvider>
      </MemoryRouter>
    </AntdApp>,
  )
}

function buildRow(id: string, name: string, manageable?: boolean): SubscribedAppRow {
  return {
    id,
    name,
    avatar_url: '',
    description: '',
    visibility_lock: false,
    visibility_template: 'all',
    admin_scope_mode: 'all_admin',
    manageable,
    configured: false,
    visibility: 'all',
    whitelist_count: 0,
  }
}

beforeEach(() => {
  localStorage.clear()
  setRefreshToken('bxt_test')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('TenantAppAdminListPage 应用配置入口', () => {
  it('manageable=false 的行按钮置灰且不可进入，manageable=true 可点击跳转', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi([
        buildRow('101', '范围内应用', true),
        buildRow('102', '范围外应用', false),
        buildRow('103', '旧数据未带标记应用'),
      ]),
    )
    renderPage()

    await waitFor(
      () => expect(screen.getByText('范围内应用')).toBeInTheDocument(),
      { timeout: 10000, interval: 50 },
    )

    const disabledButton = screen
      .getByText('范围外应用')
      .closest('tr')!
      .querySelector('button') as HTMLButtonElement
    expect(disabledButton.disabled).toBe(true)
    expect(disabledButton).toHaveTextContent('应用配置')

    // 旧数据缺失 manageable 时保持可用（undefined !== false）
    const legacyButton = screen
      .getByText('旧数据未带标记应用')
      .closest('tr')!
      .querySelector('button') as HTMLButtonElement
    expect(legacyButton.disabled).toBe(false)

    const okButton = screen
      .getByText('范围内应用')
      .closest('tr')!
      .querySelector('button') as HTMLButtonElement
    fireEvent.click(okButton)
    expect(await screen.findByText('detail-marker')).toBeInTheDocument()
  })
})
