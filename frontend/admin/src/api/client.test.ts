import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getRefreshToken, setRefreshToken } from '../auth/tokenStore'
import { request } from './client'

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

const refreshBody = {
  access_token: 'access-new',
  token_type: 'bearer',
  expires_in: 1800,
  refresh_token: 'bxt_new',
  refresh_expires_in: 1209600,
  user: {},
}

beforeEach(() => {
  localStorage.clear()
  setRefreshToken('bxt_old')
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('request', () => {
  it('204 响应返回 undefined', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(request('/admin/tools/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('错误响应携带 request_id、错误码与 Retry-After', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({ detail: '账号已锁定', code: 'ACCOUNT_LOCKED', request_id: 'rid-1' }, 429, {
          'Retry-After': '60',
        }),
      ),
    )

    await expect(
      request('/admin/auth/login', {
        method: 'POST',
        body: JSON.stringify({}),
        skipRefresh: true,
      }),
    ).rejects.toMatchObject({
      status: 429,
      code: 'ACCOUNT_LOCKED',
      requestId: 'rid-1',
      retryAfterSeconds: 60,
      message: '账号已锁定',
    })
  })

  it('GET 请求在网络异常时按退避重试', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('fetch failed'))
      .mockResolvedValueOnce(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    const promise = request<{ ok: boolean }>('/admin/plugins')
    await vi.advanceTimersByTimeAsync(300)
    await expect(promise).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('POST 请求超时抛出 TIMEOUT', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            )
          }),
      ),
    )

    const promise = request('/admin/plugins', { method: 'POST', body: '{}' })
    const assertion = expect(promise).rejects.toMatchObject({ status: 0, code: 'TIMEOUT' })
    await vi.advanceTimersByTimeAsync(15_000)
    await assertion
  })

  it('并发 401 只触发一次刷新并重放请求', async () => {
    let refreshCalls = 0
    let itemCalls = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/admin/auth/refresh')) {
        refreshCalls += 1
        return jsonResponse(refreshBody)
      }
      itemCalls += 1
      if (itemCalls <= 2) {
        return jsonResponse({ detail: '令牌已失效', code: 'UNAUTHORIZED' }, 401)
      }
      return jsonResponse({ ok: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    const [first, second] = await Promise.all([
      request<{ ok: boolean }>('/admin/plugins'),
      request<{ ok: boolean }>('/admin/plugins'),
    ])

    expect(first).toEqual({ ok: true })
    expect(second).toEqual({ ok: true })
    expect(refreshCalls).toBe(1)
    expect(getRefreshToken()).toBe('bxt_new')
  })

  it('登录接口 401 不触发刷新', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ detail: '用户名或密码错误', code: 'INVALID_CREDENTIALS' }, 401),
      )
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      request('/admin/auth/login', {
        method: 'POST',
        body: '{}',
        skipAuth: true,
        skipRefresh: true,
      }),
    ).rejects.toMatchObject({ status: 401, code: 'INVALID_CREDENTIALS' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
