/**
 * 租户作用域标识：线上由子域名决定，本地回环主机通过 ?tenant= 或请求头模拟。
 * 该值仅作为 X-Tenant-Code 使用，后端非 local 环境默认忽略该请求头。
 */

const STORAGE_KEY = 'boxia.user-tenant-code'

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

/** 读取 ?tenant= 参数并规范化，用于本地调试。 */
export function getTenantParam(): string | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  if (!params.has('tenant')) return null
  return (params.get('tenant') ?? '').trim().toLowerCase()
}

/** 本地回环主机才展示租户编码输入框。 */
export function isLocalHost(): boolean {
  if (typeof window === 'undefined') return false
  return ['localhost', '127.0.0.1', '::1', '[::1]'].includes(window.location.hostname)
}
