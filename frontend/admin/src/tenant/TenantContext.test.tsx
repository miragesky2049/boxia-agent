import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TenantGate, TenantProvider } from './TenantContext'
import { setTenantCode } from './scope'

const STORAGE_KEY = 'boxia.tenant-code'

const platformContext = {
  scope: 'platform',
  tenant: null,
  app_env: 'local',
  tenant_resolution: 'header',
  tenant_switch_mode: 'header',
  root_domain: 'localhost',
  platform_admin_subdomain: 'platform',
  platform_admin_host: 'platform.localhost',
  platform_name: 'Boxia',
  password_policy: { min_length: 10, max_bytes: 72, min_categories: 3 },
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function renderGate() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <TenantProvider>
        <TenantGate>
          <div>gate-ok</div>
        </TenantGate>
      </TenantProvider>
    </MemoryRouter>,
  )
}

describe('TenantContext 作用域容错', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/login')
    setTenantCode('')
    window.localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('残留 X-Tenant-Code 致 context 404 时，清空脏值并重试恢复', async () => {
    setTenantCode('legacy-admin')
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers)
      const pathname = new URL(String(_input), 'http://localhost').pathname
      if (pathname.endsWith('/public/context')) {
        return headers.get('x-tenant-code')
          ? jsonResponse({ detail: '租户不存在：legacy-admin', code: 'NOT_FOUND' }, 404)
          : jsonResponse(platformContext)
      }
      if (pathname.endsWith('/public/tenants')) return jsonResponse([])
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderGate()

    await waitFor(() => expect(screen.getByText('gate-ok')).toBeTruthy())
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()

    const contextCalls = fetchMock.mock.calls.filter(([input]) =>
      String(input).includes('/public/context'),
    )
    expect(contextCalls).toHaveLength(2)
    const firstHeaders = new Headers((contextCalls[0]![1] as RequestInit).headers)
    const secondHeaders = new Headers((contextCalls[1]![1] as RequestInit).headers)
    expect(firstHeaders.get('x-tenant-code')).toBe('legacy-admin')
    expect(secondHeaders.get('x-tenant-code')).toBeNull()
  })

  it('?tenant=platform 归一化为产品级，不写入保留字', async () => {
    window.history.replaceState({}, '', '/login?tenant=platform')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const pathname = new URL(String(input), 'http://localhost').pathname
        if (pathname.endsWith('/public/context')) return jsonResponse(platformContext)
        if (pathname.endsWith('/public/tenants')) return jsonResponse([])
        return jsonResponse({ detail: 'not found' }, 404)
      }),
    )

    renderGate()

    await waitFor(() => expect(screen.getByText('gate-ok')).toBeTruthy())
    expect(window.localStorage.getItem(STORAGE_KEY)).not.toBe('platform')
  })
})
