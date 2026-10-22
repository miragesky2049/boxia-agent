/**
 * 租户作用域标识：部署环境由子域名决定，本地回环主机通过请求头模拟。
 * 该值仅作为 X-Tenant-Code 使用，后端非 local 环境默认忽略该请求头。
 */

import type { PublicContext } from '../api/types'

const STORAGE_KEY = 'boxia.tenant-code'
// 与后端租户编码、平台子域名保持一致的一级标签格式
const TENANT_CODE_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/

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

/** 读取 ?tenant= 参数（仅开发调试使用，是否生效由服务端开关决定）。 */
export function getTenantParam(): string | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  if (!params.has('tenant')) return null
  return (params.get('tenant') ?? '').trim().toLowerCase()
}

/** 从地址栏移除 tenant 参数，避免刷新时重复触发切换。 */
export function clearTenantParam(): void {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  if (!url.searchParams.has('tenant')) return
  url.searchParams.delete('tenant')
  window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
}

/** 校验租户编码是否为一级域名标签。 */
export function isValidTenantCode(code: string): boolean {
  return TENANT_CODE_PATTERN.test(code.trim().toLowerCase())
}

/** 按当前协议与端口拼接目标作用域的登录地址；参数非法时返回 null。 */
export function buildTenantUrl(
  code: string,
  context: Pick<PublicContext, 'platform_admin_host' | 'root_domain'>,
): string | null {
  if (typeof window === 'undefined') return null
  const normalized = code.trim().toLowerCase()
  if (!normalized) return null
  if (normalized !== PLATFORM_TENANT_CODE && !isValidTenantCode(normalized)) return null

  const root = context.root_domain.trim().toLowerCase()
  if (!root) return null
  const hostname =
    normalized === PLATFORM_TENANT_CODE ? context.platform_admin_host : `${normalized}.${root}`
  if (!hostname) return null

  const port = window.location.port ? `:${window.location.port}` : ''
  return `${window.location.protocol}//${hostname}${port}/login`
}
