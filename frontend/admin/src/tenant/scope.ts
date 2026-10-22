/**
 * 租户作用域标识：生产环境由子域名决定，本地开发通过请求头模拟。
 * 该值仅作为 X-Tenant-Code 使用，后端生产环境默认忽略该请求头。
 */

const STORAGE_KEY = 'boxia.tenant-code'

export const PLATFORM_TENANT_CODE = 'platform'

let cached: string | null = null

export function getTenantCode(): string {
  if (cached !== null) return cached
  if (typeof window === 'undefined') {
    cached = ''
    return cached
  }
  try {
    cached = (window.localStorage.getItem(STORAGE_KEY) ?? '').trim().toLowerCase()
  } catch {
    cached = ''
  }
  return cached
}

export function setTenantCode(code: string): void {
  const normalized = code.trim().toLowerCase()
  cached = normalized
  if (typeof window === 'undefined') return
  try {
    if (normalized) {
      window.localStorage.setItem(STORAGE_KEY, normalized)
    } else {
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // 隐私模式等场景写入失败时仍使用内存值
  }
}

/** 支持通过 ?tenant=acme 分享开发调试链接，返回是否发生了切换。 */
export function applyTenantFromUrl(): boolean {
  if (typeof window === 'undefined') return false
  const params = new URLSearchParams(window.location.search)
  if (!params.has('tenant')) return false
  const code = (params.get('tenant') ?? '').trim()
  setTenantCode(code)
  return true
}
