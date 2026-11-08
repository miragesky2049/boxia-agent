import { App as AntdApp } from 'antd'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from '../../../auth/tokenStore'
import EvalCaptureButton from './EvalCaptureButton'

// T-d6：run 记录「加入评测集」捕获按钮（F18.2 冷启动主通道前端侧）。

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface FetchCall {
  method: string
  pathname: string
  body?: unknown
}

let calls: FetchCall[] = []
let datasetsBody: unknown = { items: [] }

function setupFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const pathname = new URL(String(input), 'http://localhost').pathname
    const method = (init?.method ?? 'GET').toUpperCase()
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, pathname, body })
    if (method === 'GET' && pathname.endsWith('/admin/eval/datasets'))
      return jsonResponse(datasetsBody)
    if (method === 'POST' && pathname.endsWith('/cases/from-run')) {
      return jsonResponse(
        {
          id: 'c-new',
          dataset_id: 'd1',
          input: { message: 'q' },
          expected: null,
          expected_tool_calls: null,
          position: 0,
        },
        201,
      )
    }
    return jsonResponse({ items: [] })
  })
  vi.stubGlobal('fetch', fetchMock)
}

beforeEach(() => {
  setAccessToken('t')
  calls = []
  datasetsBody = {
    items: [{ id: 'd1', application_id: 'app-1', name: '问答基线集', description: '' }],
  }
  setupFetch()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderButton() {
  return render(
    <AntdApp>
      <EvalCaptureButton applicationId="app-1" runId="run-9" />
    </AntdApp>,
  )
}

describe('EvalCaptureButton', () => {
  it('点击拉数据集，选定后提交 from-run 并提示成功', async () => {
    renderButton()
    fireEvent.click(screen.getByRole('button', { name: '加入评测集' }))
    await waitFor(() => expect(screen.getByText('问答基线集')).toBeTruthy())
    expect(
      calls.some((c) => c.method === 'GET' && c.pathname.endsWith('/admin/eval/datasets')),
    ).toBe(true)

    fireEvent.click(screen.getByRole('radio', { name: '问答基线集' }))
    fireEvent.click(screen.getByRole('button', { name: '导 入' }))
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && c.pathname.includes('/datasets/d1/cases/from-run'),
        ),
      ).toBe(true),
    )
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({ run_id: 'run-9' })
    expect(await screen.findByText('已加入评测集')).toBeTruthy()
  })

  it('无数据集时给空态提示且导入不可用', async () => {
    datasetsBody = { items: [] }
    renderButton()
    fireEvent.click(screen.getByRole('button', { name: '加入评测集' }))
    expect(await screen.findByText('还没有评测数据集，请先在「智能体评测」工作区创建')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '导 入' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(false))
  })
})
