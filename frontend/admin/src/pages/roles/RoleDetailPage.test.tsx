import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setRefreshToken } from '../../auth/tokenStore'
import { AuthProvider } from '../../auth/AuthContext'
import RoleDetailPage from './RoleDetailPage'

const adminUser = {
  id: 1,
  username: 'admin',
  display_name: '管理员',
  role_id: 1,
  role_code: 'tenant-admin',
  role_name: '租户管理员',
  tenant_id: 9,
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
  role_code: 'tenant-admin',
  role_name: '租户管理员',
  permissions: ['page:roles', 'button:role:grant'],
  menus: ['roles'],
  app_env: 'local',
  tenant_resolution: 'host',
  tenant_switch_mode: 'none',
  root_domain: 'example.com',
  platform_admin_subdomain: 'adminsystem',
  platform_admin_host: 'adminsystem.example.com',
  platform_name: 'Boxia',
  password_policy: { min_length: 10, max_bytes: 72, min_categories: 3 },
}

const role = {
  id: 5,
  tenant_id: 9,
  code: 'ops',
  name: '运营角色',
  description: '',
  is_system: false,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const pagePermission = {
  id: 11,
  code: 'page:agents',
  name: '查看智能体',
  category: 'page',
  action: 'view',
  description: '',
  sort_order: 110,
}

const createPermission = {
  id: 21,
  code: 'button:agent:create',
  name: '新建智能体',
  category: 'button',
  action: 'create',
  description: '',
  sort_order: 210,
}

const deletePermission = {
  id: 22,
  code: 'button:agent:delete',
  name: '删除智能体',
  category: 'button',
  action: 'delete',
  description: '',
  sort_order: 212,
}

const catalog = [pagePermission, createPermission, deletePermission]

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function emptyPage() {
  return { items: [], total: 0, page: 1, page_size: 10 }
}

function mockApi(onSave?: (codes: string[]) => void) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url.endsWith('/admin/auth/refresh')) {
      return jsonResponse({
        access_token: 'access',
        token_type: 'bearer',
        expires_in: 1800,
        refresh_token: 'bxt_test',
        refresh_expires_in: 1209600,
        user: adminUser,
      })
    }
    if (url.endsWith('/admin/context')) return jsonResponse(adminContext)
    if (url.endsWith('/admin/roles/5') && method === 'GET') return jsonResponse(role)
    if (url.endsWith('/admin/roles/5/grants/summary')) return jsonResponse({ counts: {} })
    if (url.endsWith('/admin/permissions')) return jsonResponse(catalog)
    if (url.endsWith('/admin/roles/5/permissions') && method === 'GET') {
      return jsonResponse({ items: [], codes: [] })
    }
    if (url.endsWith('/admin/roles/5/permissions') && method === 'PUT') {
      const codes = (JSON.parse(String(init?.body)) as { codes: string[] }).codes
      onSave?.(codes)
      return jsonResponse({ items: catalog.filter((item) => codes.includes(item.code)), codes })
    }
    if (url.includes('/admin/roles/5/grants?')) return jsonResponse(emptyPage())
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/roles/5']}>
        <AuthProvider>
          <Routes>
            <Route path="/roles/:id" element={<RoleDetailPage />} />
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

describe('RoleDetailPage 功能权限', () => {
  it('勾选权限后保存会提交所选编码', async () => {
    let savedCodes: string[] | null = null
    vi.stubGlobal(
      'fetch',
      mockApi((codes) => (savedCodes = codes)),
    )

    renderPage()

    const checkbox = await screen.findByRole('checkbox', { name: /查看智能体/ })
    await waitFor(() => expect(checkbox).toBeEnabled())
    fireEvent.click(checkbox)
    expect(checkbox).toBeChecked()
    expect(screen.getByRole('tab', { name: /页面 1\/1/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /保存/ }))

    await waitFor(() => expect(savedCodes).toEqual(['page:agents']))
  })

  it('按分类切换页签并支持整类全选与取消', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderPage()

    expect(await screen.findByRole('tab', { name: /页面/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /操作按钮 0\/2/ })).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /新建智能体/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /操作按钮/ }))

    const create = await screen.findByRole('checkbox', { name: /新建智能体/ })
    const remove = screen.getByRole('checkbox', { name: /删除智能体/ })
    await waitFor(() => expect(create).toBeEnabled())

    fireEvent.click(screen.getByRole('checkbox', { name: '全选本类' }))
    expect(create).toBeChecked()
    expect(remove).toBeChecked()
    expect(screen.getByRole('tab', { name: /操作按钮 2\/2/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('checkbox', { name: '全选本类' }))
    expect(create).not.toBeChecked()
    expect(remove).not.toBeChecked()
    expect(screen.getByRole('tab', { name: /操作按钮 0\/2/ })).toBeInTheDocument()
  })

  it('数据授权是独立页签', async () => {
    vi.stubGlobal('fetch', mockApi())
    renderPage()

    expect(await screen.findByRole('checkbox', { name: /查看智能体/ })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: '数据授权' }))

    expect(await screen.findByPlaceholderText('搜索名称或描述')).toBeInTheDocument()
    expect(screen.getByText('仅看已授权')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /查看智能体/ })).not.toBeInTheDocument()
  })
})
