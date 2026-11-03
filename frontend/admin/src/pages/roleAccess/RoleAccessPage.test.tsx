import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import RoleAccessPage from './RoleAccessPage'

const adminUser = {
  id: '1',
  username: 'tacme',
  display_name: '租户管理员',
  role_id: '2',
  role_code: 'admin',
  role_name: '管理员',
  tenant_id: '9',
  is_platform: false,
  is_active: true,
  must_change_password: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const adminContext = {
  scope: 'tenant',
  tenant: null,
  user: adminUser,
  role_code: 'admin',
  role_name: '管理员',
  permissions: ['page:role-access', 'button:role:grant'],
  menus: ['role-access'],
  app_env: 'local',
  tenant_resolution: 'host',
  tenant_switch_mode: 'none',
  root_domain: 'example.com',
  platform_admin_subdomain: 'adminsystem',
  platform_admin_host: 'adminsystem.example.com',
  platform_name: 'Boxia',
  password_policy: { min_length: 10, max_bytes: 72, min_categories: 3 },
}

const roles = [
  {
    id: 's1',
    tenant_id: '9',
    code: 'superadmin',
    name: '超级管理员',
    description: '',
    is_system: true,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'o1',
    tenant_id: '9',
    code: 'ops',
    name: '运营角色',
    description: '',
    is_system: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const rowWide = {
  resource_id: 'w1',
  name: '全员工具',
  description: '',
  is_platform: false,
  is_enabled: true,
  updated_at: '2026-01-01T00:00:00Z',
  is_granted: true,
  is_tenant_wide: true,
}

const rowRole = {
  resource_id: 'g1',
  name: '角色工具',
  description: '',
  is_platform: true,
  is_enabled: true,
  updated_at: '2026-01-01T00:00:00Z',
  is_granted: true,
  is_tenant_wide: false,
}

const rowCandidate = {
  resource_id: 'c1',
  name: '停用工具',
  description: '',
  is_platform: false,
  is_enabled: false,
  updated_at: '2026-01-01T00:00:00Z',
  is_granted: false,
  is_tenant_wide: false,
}

interface Captured {
  requests: { method: string; pathname: string; body: unknown }[]
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function noContent() {
  return new Response(null, { status: 204 })
}

function mockApi(captured: Captured) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const u = new URL(url, 'http://localhost')
    const pathname = u.pathname
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
        user: adminUser,
      })
    }
    if (pathname.endsWith('/admin/context')) return jsonResponse(adminContext)
    if (pathname.endsWith('/admin/roles') && method === 'GET') return jsonResponse(roles)
    if (pathname.endsWith('/grants/summary')) {
      return jsonResponse({ counts: { app: 0, tool: 2, skill: 0, prompt: 0, knowledge: 0 } })
    }
    if (pathname.endsWith('/admin/roles/o1/grants') && method === 'GET') {
      const type = u.searchParams.get('resource_type')
      if (type === 'tool') {
        return jsonResponse({
          items: [rowWide, rowRole, rowCandidate],
          total: 3,
          page: 1,
          page_size: 20,
        })
      }
      return jsonResponse({ items: [], total: 0, page: 1, page_size: 20 })
    }
    if (pathname.endsWith('/admin/roles/o1/grants/tool') && method === 'POST') {
      record()
      return jsonResponse({ updated: 1 })
    }
    if (pathname.endsWith('/admin/roles/o1/grants/tool/w1') && method === 'DELETE') {
      record()
      return noContent()
    }
    if (pathname.endsWith('/admin/roles/o1/grants/tool/g1/tenant-wide') && method === 'PUT') {
      record()
      return noContent()
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/role-access']}>
        <AuthProvider>
          <Routes>
            <Route path="/role-access" element={<RoleAccessPage />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </AntdApp>,
  )
}

async function switchToToolTab() {
  renderPage()
  const menuItem = await screen.findByRole('menuitem', { name: /工具/ }, { timeout: 3000 })
  fireEvent.click(menuItem)
  expect(await screen.findByText('全员工具', {}, { timeout: 3000 })).toBeInTheDocument()
}

beforeEach(() => {
  localStorage.clear()
  setRefreshToken('bxt_test')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RoleAccessPage', () => {
  it('候选表格展示全员可见与已停用标记及开通说明', async () => {
    vi.stubGlobal('fetch', mockApi({ requests: [] }))
    await switchToToolTab()

    expect(screen.getByText('全员可见')).toBeInTheDocument()
    expect(screen.getByText('已停用')).toBeInTheDocument()
    expect(screen.getByText(/候选仅包含已开通/)).toBeInTheDocument()
    // 全员可见行不参与批量勾选
    const wideRow = screen.getByText('全员工具').closest('tr')
    expect(wideRow?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.disabled).toBe(true)
  })

  it('批量授权提交未授权候选', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    await switchToToolTab()

    const row = screen.getByText('停用工具').closest('tr')
    const checkbox = row?.querySelector<HTMLInputElement>('input[type="checkbox"]')
    if (!checkbox) throw new Error('未找到候选行选择框')
    fireEvent.click(checkbox)
    fireEvent.click(screen.getByRole('button', { name: /批量授权/ }))

    await waitFor(() => expect(captured.requests).toHaveLength(1))
    expect(captured.requests[0]).toMatchObject({
      method: 'POST',
      pathname: '/api/v1/admin/roles/o1/grants/tool',
      body: { resource_ids: ['c1'] },
    })
    expect(await screen.findByText('已授权 1 项', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('取消全员可见先展示降级提示再提交单资源移除', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    await switchToToolTab()

    fireEvent.click(screen.getByRole('button', { name: '取消全员可见' }))
    expect(await screen.findByText('将降级为按角色授权，仅保留其余角色')).toBeInTheDocument()
    // antd 会在两字中文按钮中自动插入空格（确 认），用正则匹配
    fireEvent.click(screen.getByRole('button', { name: /^确\s*认$/ }))

    await waitFor(() =>
      expect(
        captured.requests.some((r) => r.method === 'DELETE' && r.pathname.endsWith('/w1')),
      ).toBe(true),
    )
  })

  it('已授权角色档资源可设为全员可见', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    await switchToToolTab()

    fireEvent.click(screen.getByRole('button', { name: '设为全员可见' }))

    await waitFor(() =>
      expect(
        captured.requests.some((r) => r.method === 'PUT' && r.pathname.endsWith('/tenant-wide')),
      ).toBe(true),
    )
  })
})
