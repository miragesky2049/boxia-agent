import { App as AntdApp } from 'antd'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ApplyWorkbench from './ApplyWorkbench'

const applyRow = {
  id: 'ap1',
  tenant_id: '9',
  application_id: 'a1',
  apply_type: 'BUY',
  status: 'SUBMITTED',
  expect_text: '需要生产使用',
  contact: '13800000000',
  sales_user_id: null,
  audit_msg: '',
  contract_no: '',
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-01T10:00:00Z',
  application_name: '智能客服',
  sales_username: null,
}

const dashboardStats = {
  pending_count: 1,
  pass_pending_count: 2,
  finished_count: 3,
  rejected_count: 4,
  last_7d_count: 5,
  active_grants: 6,
  wait_effect_grants: 7,
  expired_grants: 8,
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
]

interface Captured {
  passBodies: Record<string, unknown>[]
  rejectBodies: Record<string, unknown>[]
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(captured: Captured) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = new URL(String(input), 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    if (u.pathname.endsWith('/admin/applies/ops/pending')) {
      return jsonResponse([applyRow])
    }
    if (u.pathname.endsWith('/admin/applies/ops/dashboard')) {
      return jsonResponse(dashboardStats)
    }
    if (u.pathname.endsWith('/public/tenants')) {
      return jsonResponse(tenants)
    }
    if (method === 'POST' && /\/admin\/applies\/[^/]+\/pass$/.test(u.pathname)) {
      captured.passBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return jsonResponse({ ok: true, instance_id: null })
    }
    if (method === 'POST' && /\/admin\/applies\/[^/]+\/reject$/.test(u.pathname)) {
      captured.rejectBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return jsonResponse({ ok: true })
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter initialEntries={['/apply-workbench']}>
        <Routes>
          <Route path="/apply-workbench" element={<ApplyWorkbench />} />
        </Routes>
      </MemoryRouter>
    </AntdApp>,
  )
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ApplyWorkbench', () => {
  it('展示待审核队列与仪表盘统计并映射租户名', async () => {
    vi.stubGlobal('fetch', mockApi({ passBodies: [], rejectBodies: [] }))
    renderPage()

    expect(await screen.findByText('智能客服', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('租户A')).toBeInTheDocument()
    expect(screen.getByText('未认领')).toBeInTheDocument()
    expect(screen.getByText('购买')).toBeInTheDocument()
    expect(screen.getByText('待审核')).toBeInTheDocument()
    expect(screen.getByText('通过待开通')).toBeInTheDocument()
    expect(screen.getByText('生效中权益')).toBeInTheDocument()
  })

  it('通过（不填开通参数）提交后进入待开通提示并刷新队列', async () => {
    const captured: Captured = { passBodies: [], rejectBodies: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    renderPage()

    expect(await screen.findByText('智能客服', {}, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^通\s*过$/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认通过' }))

    await waitFor(() => expect(captured.passBodies).toHaveLength(1))
    const passBody = captured.passBodies[0]
    expect(passBody).toMatchObject({ audit_msg: '', contract_no: '' })
    expect(passBody?.grant_start_time).toBeUndefined()
    expect(
      await screen.findByText('已通过，进入待开通列表（未填开通参数）', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
  })

  it('拒绝必填原因，提交后调用 reject 接口', async () => {
    const captured: Captured = { passBodies: [], rejectBodies: [] }
    vi.stubGlobal('fetch', mockApi(captured))
    renderPage()

    expect(await screen.findByText('智能客服', {}, { timeout: 3000 })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^拒\s*绝$/ }))
    fireEvent.click(await screen.findByRole('button', { name: '确认拒绝' }))

    expect(await screen.findByText('请填写拒绝原因', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(captured.rejectBodies).toHaveLength(0)

    fireEvent.change(screen.getByPlaceholderText('将反馈给申请租户'), {
      target: { value: '预算不足' },
    })
    fireEvent.click(screen.getByRole('button', { name: '确认拒绝' }))

    await waitFor(() => expect(captured.rejectBodies).toHaveLength(1))
    expect(captured.rejectBodies[0]).toEqual({ audit_msg: '预算不足' })
    expect(await screen.findByText('已拒绝该申请', {}, { timeout: 3000 })).toBeInTheDocument()
  })
})
