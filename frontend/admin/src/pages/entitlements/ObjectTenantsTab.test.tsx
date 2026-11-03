import { App as AntdApp } from 'antd'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useSearchParams } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ObjectTenantsTab from './ObjectTenantsTab'

interface Captured {
  objectUrls: string[]
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(captured: Captured) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const u = new URL(String(input), 'http://localhost')
    if (u.pathname.includes('/admin/entitlements/objects/')) {
      captured.objectUrls.push(`${u.pathname}?${u.searchParams.toString()}`)
      return jsonResponse({
        items: [
          {
            tenant_id: '9',
            tenant_name: '租户A',
            status: 'active',
            auth_source: 'OPS',
            granted_at: '2026-01-02T00:00:00Z',
          },
          {
            tenant_id: '10',
            tenant_name: '',
            status: 'revoked',
            auth_source: 'MARKET_APPLY',
            granted_at: null,
          },
        ],
        total: 2,
        page: 1,
        page_size: 20,
      })
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function TenantProbe() {
  const [searchParams] = useSearchParams()
  return <div data-testid="probe">{searchParams.get('tenant') ?? 'none'}</div>
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ObjectTenantsTab', () => {
  it('反查列表展示状态与来源并可跳转租户开通页', async () => {
    const captured: Captured = { objectUrls: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    render(
      <AntdApp>
        <MemoryRouter initialEntries={['/objects']}>
          <Routes>
            <Route path="/objects" element={<ObjectTenantsTab objectType="tool" objectId="r1" />} />
            <Route path="/entitlements" element={<TenantProbe />} />
          </Routes>
        </MemoryRouter>
      </AntdApp>,
    )

    expect(await screen.findByText('租户A', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(captured.objectUrls[0]).toContain('/admin/entitlements/objects/tool/r1/tenants')
    expect(screen.getByText('生效中')).toBeInTheDocument()
    expect(screen.getByText('运营开通')).toBeInTheDocument()
    expect(screen.getByText('市场申请')).toBeInTheDocument()

    fireEvent.click(screen.getByText('租户A'))
    expect(await screen.findByTestId('probe', {}, { timeout: 3000 })).toHaveTextContent('9')
  })

  it('租户名为空时展示 ID 前缀并可跳转', async () => {
    const captured: Captured = { objectUrls: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    render(
      <AntdApp>
        <MemoryRouter initialEntries={['/objects']}>
          <Routes>
            <Route path="/objects" element={<ObjectTenantsTab objectType="app" objectId="a1" />} />
            <Route path="/entitlements" element={<TenantProbe />} />
          </Routes>
        </MemoryRouter>
      </AntdApp>,
    )

    expect(await screen.findByText('10', {}, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByText('10'))
    expect(await screen.findByTestId('probe', {}, { timeout: 3000 })).toHaveTextContent('10')
  })
})
