import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../auth/tokenStore'
import { AuthProvider } from '../auth/AuthContext'
import { TenantProvider } from '../tenant/TenantContext'
import TenantsPage from './TenantsPage'

const passwordPolicy = { min_length: 10, max_bytes: 72, min_categories: 3 }

const platformRow = {
  id: '00000000-0000-0000-0000-000000000000',
  code: 'platform',
  name: '产品级平台',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}
const acmeRow = {
  id: '9',
  code: 'acme',
  name: 'Acme 公司',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}
const betaRow = {
  id: '10',
  code: 'beta',
  name: 'Beta 科技',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

interface Captured {
  requests: { method: string; pathname: string; search: string; body: unknown }[]
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface MockApiOptions {
  permissions: string[]
  deleteStatus?: number
  batchResponse?: unknown
}

function mockApi(captured: Captured, options: MockApiOptions) {
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
  const publicContext = {
    scope: 'platform',
    tenant: null,
    app_env: 'local',
    tenant_resolution: 'host',
    tenant_switch_mode: 'none',
    root_domain: 'example.com',
    platform_admin_subdomain: 'adminsystem',
    platform_admin_host: 'adminsystem.example.com',
    platform_name: 'Boxia',
    password_policy: passwordPolicy,
  }
  const adminContext = {
    scope: 'platform',
    tenant: null,
    user: adminUser,
    role_code: 'superadmin',
    role_name: '超级管理员',
    permissions: options.permissions,
    menus: ['tenants'],
    app_env: 'local',
    tenant_resolution: 'host',
    tenant_switch_mode: 'none',
    root_domain: 'example.com',
    platform_admin_subdomain: 'adminsystem',
    platform_admin_host: 'adminsystem.example.com',
    platform_name: 'Boxia',
    password_policy: passwordPolicy,
  }
  let latest = [platformRow, acmeRow, betaRow]
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const u = new URL(url, 'http://localhost')
    const pathname = u.pathname
    const record = () =>
      captured.requests.push({
        method,
        pathname,
        search: u.search,
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
    if (pathname.endsWith('/public/context')) return jsonResponse(publicContext)
    if (pathname.endsWith('/public/tenants')) return jsonResponse([])
    if (pathname.endsWith('/admin/context')) return jsonResponse(adminContext)
    if (method === 'GET' && pathname.endsWith('/admin/tenants')) {
      return jsonResponse({ items: latest, total: latest.length, page: 1, page_size: 10 })
    }
    if (method === 'DELETE' && pathname.includes('/admin/tenants/')) {
      record()
      const id = pathname.split('/').pop() as string
      const status = options.deleteStatus ?? 200
      if (status === 200) {
        latest = latest.filter((row) => row.id !== id)
        return jsonResponse({
          tenant_id: id,
          code: 'deleted',
          audit_id: 'a1',
          deleted: { application: 1 },
        })
      }
      return jsonResponse(
        { detail: '该操作仅产品级运营管理平台可用', code: 'FORBIDDEN' },
        status,
      )
    }
    if (method === 'POST' && pathname.endsWith('/admin/tenants/batch')) {
      record()
      return jsonResponse(
        options.batchResponse ?? {
          total: 2,
          succeeded: 2,
          failed: 0,
          items: [
            { tenant_id: '9', code: 'acme', success: true, audit_id: 'a1' },
            { tenant_id: '10', code: 'beta', success: true, audit_id: 'a2' },
          ],
        },
      )
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/tenants']}>
        <TenantProvider>
          <AuthProvider>
            <Routes>
              <Route path="/tenants" element={<TenantsPage />} />
            </Routes>
          </AuthProvider>
        </TenantProvider>
      </MemoryRouter>
    </AntdApp>,
  )
}

const FULL_DELETE_PERMS = [
  'page:tenants',
  'button:tenant:create',
  'button:tenant:update',
  'button:tenant:delete',
]

async function waitForTableLoaded() {
  expect(await screen.findByText('Acme 公司', {}, { timeout: 3000 })).toBeInTheDocument()
}

beforeEach(() => {
  localStorage.clear()
  setRefreshToken('bxt_test')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TenantsPage 删除能力', () => {
  it('无 button:tenant:delete 权限时不渲染删除按钮与选择列', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ requests: [] }, { permissions: ['page:tenants', 'button:tenant:update'] }),
    )
    renderPage()
    await waitForTableLoaded()

    expect(screen.queryByText('删除', { exact: false })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('平台内置行删除按钮禁用且复选框不可勾选', async () => {
    vi.stubGlobal('fetch', mockApi({ requests: [] }, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    const platformRow = screen.getByText('产品级平台').closest('tr')
    const platformCheckbox = platformRow?.querySelector<HTMLInputElement>('input[type="checkbox"]')
    expect(platformCheckbox?.disabled).toBe(true)
    const deleteButtons = screen.getAllByRole('button', { name: /删\s*除/ })
    expect(deleteButtons.length).toBe(3)
    const platformDeleteButton = deleteButtons.find(
      (btn) => btn.closest('tr') === platformRow
    )
    expect(platformDeleteButton).toBeDefined()
    expect(platformDeleteButton?.hasAttribute('disabled')).toBe(true)
  })

  it('单删：Popconfirm 列出删除范围，确认后发 DELETE 并刷新', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    const targetRow = screen.getByText('Acme 公司').closest('tr')
    const deleteButton = Array.from(targetRow?.querySelectorAll('button') ?? []).find((btn) =>
      btn.textContent?.includes('删'),
    )
    expect(deleteButton).toBeTruthy()
    fireEvent.click(deleteButton as HTMLElement)

    const popconfirm = await screen.findByText(/将永久删除该租户的账号/)
    expect(popconfirm).toBeInTheDocument()
    expect(screen.getByText('不可恢复', { exact: false })).toBeInTheDocument()

    const confirmButton = screen.getByRole('button', { name: /永\s*久\s*删\s*除/ })
    fireEvent.click(confirmButton)

    await waitFor(() =>
      expect(
        captured.requests.some(
          (r) =>
            r.method === 'DELETE' && r.pathname.endsWith('/admin/tenants/9') && r.search.includes('confirm=true'),
        ),
      ).toBe(true),
    )
    expect(await screen.findByText(/已永久删除/, {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('单删接口 403 时展示后端错误信息', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal(
      'fetch',
      mockApi(captured, { permissions: FULL_DELETE_PERMS, deleteStatus: 403 }),
    )
    renderPage()
    await waitForTableLoaded()

    const targetRow = screen.getByText('Acme 公司').closest('tr')
    const deleteButton = Array.from(targetRow?.querySelectorAll('button') ?? []).find((btn) =>
      btn.textContent?.includes('删'),
    )
    fireEvent.click(deleteButton as HTMLElement)
    fireEvent.click(screen.getByRole('button', { name: /永\s*久\s*删\s*除/ }))

    expect(
      await screen.findByText('该操作仅产品级运营管理平台可用', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    // 数据行仍在（删除失败未刷新掉）
    expect(screen.getByText('Acme 公司')).toBeInTheDocument()
  })

  it('批量删除：勾选两行 → 工具栏按钮出现 → 确认后 POST 且 body 正确', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    for (const name of ['Acme 公司', 'Beta 科技']) {
      const row = screen.getByText(name).closest('tr')
      const checkbox = row?.querySelector<HTMLInputElement>('input[type="checkbox"]')
      expect(checkbox).toBeTruthy()
      fireEvent.click(checkbox as HTMLInputElement)
    }

    const batchButton = await screen.findByRole('button', { name: /批量删除（2）/ })
    fireEvent.click(batchButton)

    const confirmBtn = await screen.findByRole('button', { name: /永\s*久\s*删\s*除/ })
    fireEvent.click(confirmBtn)

    await waitFor(() =>
      expect(
        captured.requests.some(
          (r) => r.method === 'POST' && r.pathname.endsWith('/admin/tenants/batch'),
        ),
      ).toBe(true),
    )
    const batchCall = captured.requests.find((r) => r.pathname.endsWith('/admin/tenants/batch'))
    expect(batchCall?.body).toMatchObject({
      tenant_ids: ['9', '10'],
      confirm: true,
    })
    expect(
      await screen.findByText('已永久删除 2 个租户', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })

  it('批量删除部分失败时展示 warning 与失败明细', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured, {
      permissions: FULL_DELETE_PERMS,
      batchResponse: {
        total: 2,
        succeeded: 1,
        failed: 1,
        items: [
          { tenant_id: '9', code: 'acme', success: true, audit_id: 'a1' },
          {
            tenant_id: '10',
            code: 'beta',
            success: false,
            audit_id: null,
            error_code: 'FORBIDDEN',
            error: '平台租户为系统内置租户，禁止删除',
          },
        ],
      },
    }))
    renderPage()
    await waitForTableLoaded()

    for (const name of ['Acme 公司', 'Beta 科技']) {
      const row = screen.getByText(name).closest('tr')
      fireEvent.click(row?.querySelector<HTMLInputElement>('input[type="checkbox"]') as HTMLInputElement)
    }
    fireEvent.click(await screen.findByRole('button', { name: /批量删除（2）/ }))
    fireEvent.click(await screen.findByRole('button', { name: /永\s*久\s*删\s*除/ }))

    expect(await screen.findByText(/成功 1 个，失败 1 个/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(
      await screen.findByText(/平台租户为系统内置租户，禁止删除/, {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })

  it('搜索后清空勾选', async () => {
    vi.stubGlobal('fetch', mockApi({ requests: [] }, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    const checkbox = screen.getByText('Acme 公司').closest('tr')?.querySelector<HTMLInputElement>('input[type="checkbox"]')
    fireEvent.click(checkbox as HTMLInputElement)
    expect(await screen.findByRole('button', { name: /批量删除（1）/ })).toBeInTheDocument()

    const searchInput = screen.getByPlaceholderText('搜索租户名称或编码')
    fireEvent.change(searchInput, { target: { value: 'Beta' } })
    fireEvent.keyDown(searchInput, { key: 'Enter', code: 'Enter' })

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /批量删除/ })).not.toBeInTheDocument(),
    )
  })
})
