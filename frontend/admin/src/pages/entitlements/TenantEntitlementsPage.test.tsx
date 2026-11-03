import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import TenantEntitlementsPage from './TenantEntitlementsPage'

const adminUser = {
  id: '1',
  username: 'ops',
  display_name: '运营',
  role_id: '2',
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
  permissions: ['page:entitlements', 'button:entitlement:manage'],
  menus: ['entitlements'],
  app_env: 'local',
  tenant_resolution: 'host',
  tenant_switch_mode: 'none',
  root_domain: 'example.com',
  platform_admin_subdomain: 'adminsystem',
  platform_admin_host: 'adminsystem.example.com',
  platform_name: 'Boxia',
  password_policy: { min_length: 10, max_bytes: 72, min_categories: 3 },
}

const tenants = [
  {
    id: '9',
    code: 'a',
    name: '租户A',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: '10',
    code: 'b',
    name: '租户B',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const rowA = {
  object_type: 'skill',
  object_id: 's1',
  name: '权益技能A',
  status: 'active',
  auth_source: 'OPS',
  auth_type: 'FORMAL',
  start_time: null,
  expire_time: null,
  quota: {},
  remark: '',
  granted_at: null,
  is_deprecated: false,
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function emptyPage() {
  return { items: [], total: 0, page: 1, page_size: 20 }
}

function pageOf(items: unknown[], total: number, pageSize: number) {
  return { items, total, page: 1, page_size: pageSize }
}

interface Captured {
  batchBodies: Record<string, unknown>[]
}

function mockApi(captured: Captured) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const u = new URL(url, 'http://localhost')
    const pathname = u.pathname
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
    if (pathname.endsWith('/public/tenants')) return jsonResponse(tenants)
    if (method === 'GET' && pathname.includes('/admin/entitlements/tenants/')) {
      const tenantId = pathname.split('/').pop() as string
      const objectType = u.searchParams.get('object_type')
      const pageSize = Number(u.searchParams.get('page_size') ?? '20')
      if (tenantId !== '9') return jsonResponse(emptyPage())
      if (objectType === null || objectType === 'skill') {
        return jsonResponse(pageOf([rowA], 1, pageSize))
      }
      return jsonResponse({ items: [], total: 0, page: 1, page_size: pageSize })
    }
    if (method === 'POST' && pathname.endsWith('/admin/entitlements/preview')) {
      return jsonResponse({
        add: [],
        remove: [
          { view: rowA, affected_role_grants: 2, affected_role_names: ['运维角色', '财务角色'] },
        ],
        unchanged: [],
      })
    }
    if (method === 'POST' && pathname.endsWith('/admin/entitlements/batch')) {
      captured.batchBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return jsonResponse({ updated: 1, failed: [], affected_role_grants: 2 })
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/entitlements']}>
        <AuthProvider>
          <Routes>
            <Route path="/entitlements" element={<TenantEntitlementsPage />} />
          </Routes>
        </AuthProvider>
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

describe('TenantEntitlementsPage', () => {
  it('加载后默认选中最近列表首个租户并展示类型计数', async () => {
    vi.stubGlobal('fetch', mockApi({ batchBodies: [] }))
    renderPage()

    expect(await screen.findByText('权益技能A', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText(/全部（1）/)).toBeInTheDocument()
    expect(screen.getByText(/技能（1）/)).toBeInTheDocument()
  })

  it('行内取消开通：预览展示影响面，确认后提交 revoke 请求', async () => {
    const captured = { batchBodies: [] as Record<string, unknown>[] }
    vi.stubGlobal('fetch', mockApi(captured))
    renderPage()

    expect(await screen.findByText('权益技能A', {}, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '取消开通' }))

    expect(await screen.findByText(/取消后相关角色授权将失效/)).toBeInTheDocument()
    expect(screen.getByText('运维角色、财务角色')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('将记录到权益备注与审计'), {
      target: { value: '合作到期' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认执行' }))

    await waitFor(() => expect(captured.batchBodies).toHaveLength(1))
    const body = captured.batchBodies[0]
    expect(body).toMatchObject({
      tenant_id: '9',
      mode: 'revoke',
      reason: '合作到期',
      items: [{ object_type: 'skill', object_id: 's1' }],
    })
    expect(
      await screen.findByText('已更新 1 项，影响角色授权 2 项', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })

  it('切换租户后空状态展示', async () => {
    vi.stubGlobal('fetch', mockApi({ batchBodies: [] }))
    renderPage()
    expect(await screen.findByText('权益技能A', {}, { timeout: 3000 })).toBeInTheDocument()

    const [tenantSelect] = screen.getAllByRole('combobox')
    if (!tenantSelect) throw new Error('未找到租户选择器')
    fireEvent.mouseDown(tenantSelect)
    fireEvent.click(await screen.findByText('租户B（b）'))

    await waitFor(() => expect(screen.queryByText('权益技能A')).not.toBeInTheDocument())
  })
})
