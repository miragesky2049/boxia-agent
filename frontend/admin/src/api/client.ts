import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from '../auth/tokenStore'

const DEFAULT_API_BASE_URL = '/api/v1'
const REQUEST_TIMEOUT_MS = 15_000
const RETRY_BASE_DELAY_MS = 300
const MAX_ATTEMPTS = 3
const RETRYABLE_STATUS = new Set([502, 503, 504])
const NO_REFRESH_PATHS = ['/admin/auth/login', '/admin/auth/refresh', '/admin/auth/logout']

interface ApiErrorOptions {
  requestId?: string
  retryAfterSeconds?: number
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string
  readonly retryAfterSeconds?: number

  constructor(
    message: string,
    status: number,
    code = 'UNKNOWN_ERROR',
    options: ApiErrorOptions = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = options.requestId
    this.retryAfterSeconds = options.retryAfterSeconds
  }
}

export interface RequestOptions extends RequestInit {
  /** 不携带访问令牌，用于登录等匿名接口。 */
  skipAuth?: boolean
  /** 401 时不触发自动刷新，避免刷新接口自身递归。 */
  skipRefresh?: boolean
  /** 关闭 GET 自动重试。 */
  skipRetry?: boolean
}

interface ErrorPayload {
  detail?: unknown
  code?: string
  request_id?: string
  errors?: unknown
}

function apiBaseUrl(): string {
  const configured = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL
  return configured.endsWith('/') ? configured.slice(0, -1) : configured
}

function buildUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  return `${apiBaseUrl()}${path.startsWith('/') ? path : `/${path}`}`
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function backoffDelay(attempt: number): number {
  return RETRY_BASE_DELAY_MS * 2 ** (attempt - 1)
}

function parseRetryAfter(header: string | null): number | undefined {
  if (!header) return undefined
  const seconds = Number(header)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined
}

async function send(
  url: string,
  init: RequestInit,
  externalSignal?: AbortSignal | null,
): Promise<Response> {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, REQUEST_TIMEOUT_MS)

  const abort = () => controller.abort()
  if (externalSignal?.aborted) {
    controller.abort()
  } else {
    externalSignal?.addEventListener('abort', abort, { once: true })
  }

  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch {
    if (timedOut) {
      throw new ApiError('请求超时，请稍后重试', 0, 'TIMEOUT')
    }
    if (externalSignal?.aborted) {
      throw new ApiError('请求已取消', 0, 'ABORTED')
    }
    throw new ApiError('无法连接服务器，请检查网络或服务状态', 0, 'NETWORK_ERROR')
  } finally {
    clearTimeout(timer)
    externalSignal?.removeEventListener('abort', abort)
  }
}

function buildHeaders(init: RequestInit, options: RequestOptions): Headers {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  const hasBody = init.body !== undefined && init.body !== null
  const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData
  if (hasBody && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!options.skipAuth) {
    const token = getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  return headers
}

function shouldAttemptRefresh(path: string, options: RequestOptions): boolean {
  if (options.skipRefresh) return false
  return !NO_REFRESH_PATHS.some((prefix) => path.startsWith(prefix))
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const first = detail[0]
    if (first && typeof first === 'object' && 'msg' in first) {
      const msg = (first as { msg?: unknown }).msg
      if (typeof msg === 'string' && msg) return msg
    }
  }
  return null
}

async function buildApiError(response: Response, fallbackMessage: string): Promise<ApiError> {
  const data = (await response.json().catch(() => null)) as ErrorPayload | null
  return new ApiError(
    detailMessage(data?.detail) ?? fallbackMessage,
    response.status,
    data?.code ?? 'UNKNOWN_ERROR',
    {
      requestId: data?.request_id ?? response.headers.get('x-request-id') ?? undefined,
      retryAfterSeconds: parseRetryAfter(response.headers.get('retry-after')),
    },
  )
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204 || response.status === 205) {
    return undefined as T
  }
  if (!response.ok) {
    throw await buildApiError(response, '请求失败，请稍后再试')
  }
  const text = await response.text()
  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError('服务器返回了无法解析的数据', response.status, 'INVALID_RESPONSE')
  }
}

export type RefreshResult = 'ok' | 'invalid' | 'unavailable'

let refreshPromise: Promise<RefreshResult> | null = null

async function performRefresh(): Promise<RefreshResult> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return 'invalid'
  let response: Response
  try {
    response = await send(`${apiBaseUrl()}/admin/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  } catch {
    return 'unavailable'
  }
  if (!response.ok) {
    return response.status === 400 || response.status === 401 || response.status === 403
      ? 'invalid'
      : 'unavailable'
  }
  const data = (await response.json().catch(() => null)) as {
    access_token?: string
    refresh_token?: string
  } | null
  if (!data?.access_token || !data.refresh_token) return 'unavailable'
  setRefreshToken(data.refresh_token)
  setAccessToken(data.access_token)
  return 'ok'
}

async function withRefreshLock(): Promise<RefreshResult> {
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks
  if (locks?.request) {
    return locks.request('boxia-admin-refresh', performRefresh) as Promise<RefreshResult>
  }
  return performRefresh()
}

/** 单飞刷新：并发 401 只发起一次刷新，多标签页通过 Web Locks 串行。 */
export function refreshSession(): Promise<RefreshResult> {
  if (!refreshPromise) {
    refreshPromise = withRefreshLock().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

export function redirectToLogin(): void {
  if (typeof window === 'undefined') return
  const { pathname, search } = window.location
  if (pathname === '/login') return
  const next = encodeURIComponent(`${pathname}${search}`)
  window.location.assign(`/login?next=${next}`)
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { skipAuth = false, skipRefresh = false, skipRetry = false, ...init } = options
  const method = (init.method ?? 'GET').toUpperCase()
  const maxAttempts = method === 'GET' && !skipRetry ? MAX_ATTEMPTS : 1
  let attempt = 0
  let refreshed = false

  for (;;) {
    attempt += 1
    let response: Response
    try {
      response = await send(
        buildUrl(path),
        {
          ...init,
          method,
          headers: buildHeaders(init, { skipAuth, skipRefresh, skipRetry }),
        },
        init.signal,
      )
    } catch (error) {
      if (error instanceof ApiError && error.code === 'NETWORK_ERROR' && attempt < maxAttempts) {
        await sleep(backoffDelay(attempt))
        continue
      }
      throw error
    }

    if (response.status === 401 && shouldAttemptRefresh(path, { skipRefresh })) {
      if (!refreshed) {
        refreshed = true
        setAccessToken(null)
        const result = await refreshSession()
        if (result === 'ok') continue
        if (result === 'unavailable') {
          throw new ApiError('网络异常，暂时无法刷新登录状态，请稍后重试', 0, 'NETWORK_ERROR')
        }
      }
      clearSession()
      redirectToLogin()
      throw await buildApiError(response, '登录已过期，请重新登录')
    }

    if (attempt < maxAttempts && RETRYABLE_STATUS.has(response.status)) {
      await sleep(backoffDelay(attempt))
      continue
    }

    return parseResponse<T>(response)
  }
}
