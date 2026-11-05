import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import { TenantProvider } from '../../tenant/TenantContext'
import ResourcesPage from './ResourcesPage'

const passwordPolicy = { min_length: 10, max_bytes: 72, min_categories: 3 }

interface Captured {
  requests: { method: string; pathname: string; body: unknown }[]
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const platformResources = [
  {
    id: 'p1',
    type: 'tool',
    owner_type: 'platform',
    owner_id: null,
    name: '已过工具',
    config: {},
    version: 1,
    is_enabled: true,
    is_deprecated: false,
    created_at: '2026-01-01T00:00:00Z',
    review_status: 'approved',
  },
  {
    id: 'p2',
    type: 'tool',
    owner_type: 'tenant',
    owner_id: '9',
    name: '待审工具',
    config: {},
    version: 1,
    is_enabled: true,
    is_deprecated: false,
    created_at: '2026-01-01T00:00:00Z',
    review_status: 'pending',
  },
]

const tenantResources = [
  {
    id: 't1',
    type: 'tool',
    owner_type: 'platform',
    owner_id: null,
    name: '平台开通工具',
    config: {},
    version: 1,
    review_status: 'approved',
  },
  {
    id: 't2',
    type: 'tool',
    owner_type: 'tenant',
    owner_id: '9',
    name: '驳回自建工具',
    config: {},
    version: 1,
    review_status: 'rejected',
    review_remark: '需整改',
  },
  {
    id: 't3',
    type: 'tool',
    owner_type: 'tenant',
    owner_id: '9',
    name: '待审自建工具',
    config: {},
    version: 1,
    review_status: 'pending',
  },
]

function mockContext(scope: 'platform' | 'tenant', permissions: string[], captured: Captured) {
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
        user,
      })
    }
    if (pathname.endsWith('/public/context')) return jsonResponse(publicContext)
    if (pathname.endsWith('/public/tenants')) return jsonResponse([])
    if (pathname.endsWith('/admin/context')) {
      return jsonResponse({
        ...publicContext,
        user,
        role_code: user.role_code,
        role_name: user.role_name,
        permissions,
        menus: ['resources'],
      })
    }
    if (pathname.endsWith('/admin/resources') && method === 'GET') {
      return jsonResponse(platformResources)
    }
    if (pathname.endsWith('/admin/my-resources') && method === 'GET') {
      return jsonResponse(tenantResources)
    }
    if (/\/admin\/resources\/[^/]+\/review$/.test(pathname) && method === 'POST') {
      record()
      const body = (init?.body ? JSON.parse(String(init.body)) : {}) as { decision: string }
      return jsonResponse({
        resource_id: 'p2',
        review_status: body.decision === 'approve' ? 'approved' : 'rejected',
        review_remark: '',
      })
    }
    if (/\/admin\/my-resources\/[^/]+\/submit-review$/.test(pathname) && method === 'POST') {
      record()
      return jsonResponse({ resource_id: 't2', review_status: 'pending' })
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/resources']}>
        <TenantProvider>
          <AuthProvider>
            <Routes>
              <Route path="/resources" element={<ResourcesPage />} />
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

describe('ResourcesPage 平台视角', () => {
  it('待审核行展示审核入口并可提交通过', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal(
      'fetch',
      mockContext('platform', ['page:resources', 'button:resource:review'], captured),
    )
    renderPage()

    expect(await screen.findByText('待审工具', {}, { timeout: 3000 })).toBeInTheDocument()
    // antd 会在两字中文按钮中自动插入空格（审 核），用正则匹配
    const reviewButtons = screen.getAllByRole('button', { name: /^审\s*核$/ })
    expect(reviewButtons).toHaveLength(1)
    fireEvent.click(reviewButtons[0] as HTMLElement)

    expect(await screen.findByText('审核资源：待审工具')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^通\s*过$/ }))

    await waitFor(() => expect(captured.requests).toHaveLength(1))
    expect(captured.requests[0]).toMatchObject({
      method: 'POST',
      pathname: '/api/v1/admin/resources/p2/review',
      body: { decision: 'approve', remark: '' },
    })
    expect(await screen.findByText('已通过审核', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('可提交驳回', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal(
      'fetch',
      mockContext('platform', ['page:resources', 'button:resource:review'], captured),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /^审\s*核$/ }, { timeout: 3000 }))
    fireEvent.click(await screen.findByRole('button', { name: /^驳\s*回$/ }))
    await waitFor(() => expect(captured.requests).toHaveLength(1))
    expect(captured.requests[0]).toMatchObject({
      method: 'POST',
      pathname: '/api/v1/admin/resources/p2/review',
      body: { decision: 'reject', remark: '' },
    })
    expect(await screen.findByText('已驳回', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('无审核权限时不显示审核入口', async () => {
    vi.stubGlobal('fetch', mockContext('platform', ['page:resources'], { requests: [] }))
    renderPage()

    expect(await screen.findByText('待审工具', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^审\s*核$/ })).not.toBeInTheDocument()
    // 无审核权限不影响平台常规操作按钮
    expect(screen.getAllByRole('button', { name: /^编\s*辑$/ }).length).toBeGreaterThan(0)
  })
})

describe('ResourcesPage 租户视角', () => {
  it('走 my-resources 展示开通与自建并区分审核状态', async () => {
    vi.stubGlobal(
      'fetch',
      mockContext('tenant', ['page:resources', 'button:resource:create'], { requests: [] }),
    )
    renderPage()

    expect(await screen.findByText('平台开通工具', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('平台开通')).toBeInTheDocument()
    expect(screen.getAllByText('本租户自建')).toHaveLength(2)
    expect(screen.getByText('需整改')).toBeInTheDocument()
    // 仅被驳回的自建资源可重新提交审核
    expect(screen.getByRole('button', { name: '提交审核' })).toBeInTheDocument()
    expect(screen.getAllByText('待审核')).toHaveLength(1)
  })

  it('自建驳回资源提交审核后调用重新提交接口', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal(
      'fetch',
      mockContext('tenant', ['page:resources', 'button:resource:create'], captured),
    )
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: '提交审核' }, { timeout: 3000 }))
    await waitFor(() => expect(captured.requests).toHaveLength(1))
    expect(captured.requests[0]).toMatchObject({
      method: 'POST',
      pathname: '/api/v1/admin/my-resources/t2/submit-review',
    })
    expect(await screen.findByText('已重新提交审核', {}, { timeout: 3000 })).toBeInTheDocument()
  })
})
