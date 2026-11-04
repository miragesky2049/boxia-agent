import { App as AntdApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import { TenantProvider } from '../../tenant/TenantContext'
import AppListPage from './AppListPage'

const passwordPolicy = { min_length: 10, max_bytes: 72, min_categories: 3 }

const acmeApp = {
  id: '101',
  owner_type: 'platform',
  owner_id: null,
  name: '客服助手',
  avatar_url: null,
  description: '在线客服应用',
  is_enabled: true,
  is_listed_in_market: true,
  visibility_mode: 'all',
  flow_type: 'chatflow',
  created_by: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}
const betaApp = {
  id: '102',
  owner_type: 'platform',
  owner_id: null,
  name: '报表工作流',
  avatar_url: null,
  description: '定时生成报表',
  is_enabled: true,
  is_listed_in_market: false,
  visibility_mode: 'all',
  flow_type: 'workflow',
  created_by: null,
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
    menus: ['apps'],
    app_env: 'local',
    tenant_resolution: 'host',
    tenant_switch_mode: 'none',
    root_domain: 'example.com',
    platform_admin_subdomain: 'adminsystem',
    platform_admin_host: 'adminsystem.example.com',
    platform_name: 'Boxia',
    password_policy: passwordPolicy,
  }
  let latest = [acmeApp, betaApp]
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
    if (method === 'GET' && pathname.endsWith('/admin/apps')) {
      return jsonResponse(latest)
    }
    if (method === 'DELETE' && pathname.includes('/admin/apps/')) {
      record()
      const id = pathname.split('/').pop() as string
      const status = options.deleteStatus ?? 200
      if (status === 200) {
        latest = latest.filter((row) => row.id !== id)
        return jsonResponse({
          application_id: id,
          name: 'deleted',
          audit_id: 'a1',
          deleted: { run: 1 },
        })
      }
      return jsonResponse(
        { detail: '应用删除仅限平台 superadmin', code: 'FORBIDDEN' },
        status,
      )
    }
    if (method === 'POST' && pathname.endsWith('/admin/apps/batch')) {
      record()
      return jsonResponse(
        options.batchResponse ?? {
          total: 2,
          succeeded: 2,
          failed: 0,
          items: [
            { application_id: '101', name: '客服助手', success: true, audit_id: 'a1' },
            { application_id: '102', name: '报表工作流', success: true, audit_id: 'a2' },
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
      <MemoryRouter initialEntries={['/apps']}>
        <TenantProvider>
          <AuthProvider>
            <Routes>
              <Route path="/apps" element={<AppListPage />} />
            </Routes>
          </AuthProvider>
        </TenantProvider>
      </MemoryRouter>
    </AntdApp>,
  )
}

const FULL_DELETE_PERMS = [
  'page:apps',
  'button:app:create',
  'button:app:update',
  'button:app:delete',
]

async function waitForTableLoaded() {
  await waitFor(() => expect(screen.getByText('客服助手')).toBeInTheDocument(), {
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

describe('AppListPage 删除能力', () => {
  it('无 button:app:delete 权限时不渲染删除按钮与选择列', async () => {
    vi.stubGlobal(
      'fetch',
      mockApi({ requests: [] }, { permissions: ['page:apps', 'button:app:update'] }),
    )
    renderPage()
    await waitForTableLoaded()

    expect(screen.queryByText('删除', { exact: false })).not.toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('单删：Popconfirm 列出删除范围，确认后发 DELETE 并刷新', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    const targetRow = screen.getByText('客服助手').closest('tr')
    const deleteButton = Array.from(targetRow?.querySelectorAll('button') ?? []).find((btn) =>
      btn.textContent?.includes('删'),
    )
    expect(deleteButton).toBeTruthy()
    fireEvent.click(deleteButton as HTMLElement)

    const popconfirm = await screen.findByText(/将永久删除应用本体及其画布版本/)
    expect(popconfirm).toBeInTheDocument()
    expect(screen.getByText('不可恢复', { exact: false })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /永\s*久\s*删\s*除/ }))

    await waitFor(() =>
      expect(
        captured.requests.some(
          (r) =>
            r.method === 'DELETE' &&
            r.pathname.endsWith('/admin/apps/101') &&
            r.search.includes('confirm=true'),
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

    const targetRow = screen.getByText('客服助手').closest('tr')
    const deleteButton = Array.from(targetRow?.querySelectorAll('button') ?? []).find((btn) =>
      btn.textContent?.includes('删'),
    )
    fireEvent.click(deleteButton as HTMLElement)
    fireEvent.click(screen.getByRole('button', { name: /永\s*久\s*删\s*除/ }))

    expect(
      await screen.findByText('应用删除仅限平台 superadmin', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(screen.getByText('客服助手')).toBeInTheDocument()
  })

  it('批量删除：勾选两行 → 工具栏按钮出现 → 确认后 POST 且 body 正确', async () => {
    const captured: Captured = { requests: [] }
    vi.stubGlobal('fetch', mockApi(captured, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    for (const name of ['客服助手', '报表工作流']) {
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
          (r) => r.method === 'POST' && r.pathname.endsWith('/admin/apps/batch'),
        ),
      ).toBe(true),
    )
    const batchCall = captured.requests.find((r) => r.pathname.endsWith('/admin/apps/batch'))
    expect(batchCall?.body).toMatchObject({
      application_ids: ['101', '102'],
      confirm: true,
    })
    expect(
      await screen.findByText('已永久删除 2 个应用', {}, { timeout: 3000 }),
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
          { application_id: '101', name: '客服助手', success: true, audit_id: 'a1' },
          {
            application_id: '102',
            name: '报表工作流',
            success: false,
            audit_id: null,
            error_code: 'NOT_FOUND',
            error: '应用不存在',
          },
        ],
      },
    }))
    renderPage()
    await waitForTableLoaded()

    for (const name of ['客服助手', '报表工作流']) {
      const row = screen.getByText(name).closest('tr')
      fireEvent.click(
        row?.querySelector<HTMLInputElement>('input[type="checkbox"]') as HTMLInputElement,
      )
    }
    fireEvent.click(await screen.findByRole('button', { name: /批量删除（2）/ }))
    fireEvent.click(await screen.findByRole('button', { name: /永\s*久\s*删\s*除/ }))

    expect(
      await screen.findByText(/成功 1 个，失败 1 个/, {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    expect(await screen.findByText(/应用不存在/, {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('名称过滤变化后清空勾选', async () => {
    vi.stubGlobal('fetch', mockApi({ requests: [] }, { permissions: FULL_DELETE_PERMS }))
    renderPage()
    await waitForTableLoaded()

    const checkbox = screen
      .getByText('客服助手')
      .closest('tr')
      ?.querySelector<HTMLInputElement>('input[type="checkbox"]')
    fireEvent.click(checkbox as HTMLInputElement)
    expect(await screen.findByRole('button', { name: /批量删除（1）/ })).toBeInTheDocument()

    const filterInput = screen.getByPlaceholderText('按名称过滤')
    fireEvent.change(filterInput, { target: { value: '报表' } })

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /批量删除/ })).not.toBeInTheDocument(),
    )
  })
})
