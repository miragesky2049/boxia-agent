import { App as AntdApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import { TenantProvider } from '../../tenant/TenantContext'
import TenantAppDetailPage from './TenantAppDetailPage'

const passwordPolicy = { min_length: 10, max_bytes: 72, min_categories: 3 }

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

interface Captured {
  requests: { method: string; pathname: string; body: unknown }[]
}

interface MockState {
  configured: boolean
  visibility: 'all' | 'whitelist'
  whitelist: Array<{ subject_type: string; subject_id: string; include_subtree: boolean }>
  visibilityLock: boolean
  manageable?: boolean
  auxForbidden?: boolean
  putStatus?: number
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(captured: Captured, state: MockState) {
  const publicContext = {
    scope: 'tenant',
    tenant: { id: 't1', code: 'acme', name: 'Acme' },
    app_env: 'local',
    tenant_resolution: 'host',
    tenant_switch_mode: 'none',
    root_domain: 'example.com',
    platform_admin_subdomain: 'platform',
    platform_admin_host: 'platform.example.com',
    platform_name: 'Boxia',
    password_policy: passwordPolicy,
  }
  const adminContext = {
    ...publicContext,
    user: tenantUser,
    role_code: 'tenant_admin',
    role_name: '租户管理员',
    permissions: ['page:tenant-apps'],
    menus: ['tenant-apps'],
  }
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const pathname = new URL(url, 'http://localhost').pathname
    const record = () =>
      captured.requests.push({
        method,
        pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
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
    if (pathname.endsWith('/public/context')) return jsonResponse(publicContext)
    if (pathname.endsWith('/public/tenants')) return jsonResponse([])
    if (pathname.endsWith('/admin/context')) return jsonResponse(adminContext)
    if (pathname.endsWith('/admin/users/options')) {
      if (state.auxForbidden) return jsonResponse({ detail: 'forbidden' }, 403)
      return jsonResponse([{ id: 'u1', username: 'li4lei', display_name: '李雷' }])
    }
    if (pathname.endsWith('/admin/departments')) {
      if (state.auxForbidden) return jsonResponse({ detail: 'forbidden' }, 403)
      return jsonResponse([{ id: 'd1', name: '技术部', parent_id: null, children: [] }])
    }
    if (pathname.endsWith('/admin/roles')) {
      if (state.auxForbidden) return jsonResponse({ detail: 'forbidden' }, 403)
      return jsonResponse([
        {
          id: 'r1',
          code: 'ops',
          name: '运营',
          tenant_id: 't1',
          is_active: true,
          is_builtin: false,
          description: '',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ])
    }
    if (pathname.endsWith('/admin/tenant/apps/101/visibility')) {
      if (method === 'GET') {
        return jsonResponse({
          configured: state.configured,
          visibility: state.visibility,
          whitelist: state.whitelist,
          visibility_lock: state.visibilityLock,
          manageable: state.manageable ?? true,
        })
      }
      if (method === 'PUT') {
        record()
        if (state.putStatus === 403) {
          return jsonResponse({ detail: '平台已锁定该应用的可见范围', code: 'FORBIDDEN' }, 403)
        }
        const payload = JSON.parse(String(init?.body ?? '{}')) as {
          visibility: 'all' | 'whitelist'
          whitelist: MockState['whitelist']
        }
        state.configured = true
        state.visibility = payload.visibility
        state.whitelist = payload.whitelist
        return jsonResponse({
          configured: true,
          visibility: payload.visibility,
          whitelist: payload.whitelist,
          visibility_lock: state.visibilityLock,
        })
      }
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/tenant-apps/101']}>
        <TenantProvider>
          <AuthProvider>
            <Routes>
              <Route path="/tenant-apps/:appId" element={<TenantAppDetailPage />} />
            </Routes>
          </AuthProvider>
        </TenantProvider>
      </MemoryRouter>
    </AntdApp>,
  )
}

async function waitForPageLoaded() {
  await waitFor(() => expect(screen.getByRole('tab', { name: '可见范围' })).toBeInTheDocument(), {
    timeout: 10000,
    interval: 50,
  })
}

beforeEach(() => {
  localStorage.clear()
  setRefreshToken('bxt_test')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('TenantAppDetailPage 可见范围配置', () => {
  it('全员可见切白名单后出现条目编辑区', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        { requests: [] },
        {
          configured: true,
          visibility: 'all',
          whitelist: [],
          visibilityLock: false,
        },
      ),
    )
    renderPage()
    await waitForPageLoaded()

    fireEvent.click(screen.getByLabelText('白名单可见'))
    expect(await screen.findByRole('button', { name: /添加白名单条目/ })).toBeInTheDocument()
  })

  it('visibility_lock=true 时表单只读且无保存按钮', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        { requests: [] },
        {
          configured: true,
          visibility: 'whitelist',
          whitelist: [{ subject_type: 'USER', subject_id: 'u1', include_subtree: false }],
          visibilityLock: true,
        },
      ),
    )
    renderPage()
    await waitForPageLoaded()

    expect(
      await screen.findByText('平台已锁定该应用的可见范围，租户侧仅可查看'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument()
    const radio = screen.getByLabelText('全员可见') as HTMLInputElement
    expect(radio.disabled).toBe(true)
  })

  it('manageable=false（不在管理范围）时整页只读并提示', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        { requests: [] },
        {
          configured: true,
          visibility: 'all',
          whitelist: [],
          visibilityLock: false,
          manageable: false,
        },
      ),
    )
    renderPage()
    await waitForPageLoaded()

    expect(
      await screen.findByText('你不在该应用的管理范围内，当前仅可查看配置'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /保\s*存/ })).not.toBeInTheDocument()
    const radio = screen.getByLabelText('白名单可见') as HTMLInputElement
    expect(radio.disabled).toBe(true)
  })

  it('辅助下拉接口 403 不影响编辑态：manageable=true 时仍可保存', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi(
        { requests: [] },
        {
          configured: true,
          visibility: 'all',
          whitelist: [],
          visibilityLock: false,
          manageable: true,
          auxForbidden: true,
        },
      ),
    )
    renderPage()
    await waitForPageLoaded()

    expect(screen.queryByText('你不在该应用的管理范围内，当前仅可查看配置')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /保\s*存/ })).toBeInTheDocument()
    const radio = screen.getByLabelText('白名单可见') as HTMLInputElement
    expect(radio.disabled).toBe(false)
  })

  it('白名单保存时 PUT 请求体格式正确', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal(
      'fetch',
      mockApi(captured, {
        configured: false,
        visibility: 'all',
        whitelist: [],
        visibilityLock: false,
      }),
    )
    renderPage()
    await waitForPageLoaded()

    fireEvent.click(screen.getByLabelText('白名单可见'))
    fireEvent.click(await screen.findByRole('button', { name: /添加白名单条目/ }))

    const comboboxes = screen.getAllByRole('combobox')
    // 第一行为主体类型选择（默认用户），第二行为用户选择
    const userSelect = comboboxes[1] as HTMLElement
    fireEvent.mouseDown(userSelect)
    const option = await screen.findByText('李雷（li4lei）', {
      selector: '.ant-select-item-option-content',
    })
    fireEvent.click(option)

    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    await waitFor(() =>
      expect(
        captured.requests.some(
          (r) => r.method === 'PUT' && r.pathname.endsWith('/admin/tenant/apps/101/visibility'),
        ),
      ).toBe(true),
    )
    const putCall = captured.requests.find((r) => r.method === 'PUT')
    expect(putCall?.body).toEqual({
      visibility: 'whitelist',
      whitelist: [{ subject_type: 'USER', subject_id: 'u1', include_subtree: false }],
    })
    expect(await screen.findByText('可见范围已保存', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('平台锁定后保存返回 403 时提示锁定文案', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal(
      'fetch',
      mockApi(captured, {
        configured: true,
        visibility: 'all',
        whitelist: [],
        visibilityLock: false,
        putStatus: 403,
      }),
    )
    renderPage()
    await waitForPageLoaded()

    // 将 visibility 切为白名单并添加一条完整记录后保存
    fireEvent.click(screen.getByLabelText('白名单可见'))
    fireEvent.click(await screen.findByRole('button', { name: /添加白名单条目/ }))
    const comboboxes = screen.getAllByRole('combobox')
    fireEvent.mouseDown(comboboxes[1] as HTMLElement)
    fireEvent.click(
      await screen.findByText('李雷（li4lei）', { selector: '.ant-select-item-option-content' }),
    )
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }))

    expect(
      await screen.findByText('平台已锁定该应用的可见范围，租户侧不可修改', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })
})
