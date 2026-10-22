import { Result } from 'antd'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { fetchPublicContext, fetchPublicTenants } from '../api/tenant'
import type { PublicContext, Tenant } from '../api/types'
import { clearSession } from '../auth/tokenStore'
import PageLoading from '../components/PageLoading'
import { PLATFORM_TENANT_CODE, applyTenantFromUrl, getTenantCode, setTenantCode } from './scope'

interface TenantContextValue {
  context: PublicContext | null
  loading: boolean
  error: string
  isPlatform: boolean
  devTenants: Tenant[]
  platformName: string
  scopeLabel: string
  switchTenant: (code: string) => void
}

const TenantContext = createContext<TenantContextValue | null>(null)

export function TenantProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<PublicContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [devTenants, setDevTenants] = useState<Tenant[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchPublicContext()
      setContext(result)
      if (result.dev_tenant_switch) {
        fetchPublicTenants()
          .then(setDevTenants)
          .catch(() => setDevTenants([]))
      }
    } catch (err) {
      setContext(null)
      setError(err instanceof ApiError ? err.message : '无法识别当前访问域名')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') {
      void load()
      return
    }
    if (applyTenantFromUrl()) {
      // 切换作用域后旧令牌不再适用，清理地址栏参数并回到登录页重新认证。
      clearSession()
      const url = new URL(window.location.href)
      url.searchParams.delete('tenant')
      window.history.replaceState({}, '', `${url.pathname}${url.search}`)
      if (url.pathname !== '/login') {
        window.location.assign(`${url.pathname}${url.search}`)
        return
      }
    }
    void load()
  }, [load])

  const switchTenant = useCallback((code: string) => {
    if (code === (getTenantCode() || PLATFORM_TENANT_CODE)) return
    setTenantCode(code === PLATFORM_TENANT_CODE ? PLATFORM_TENANT_CODE : code)
    clearSession()
    if (typeof window !== 'undefined') {
      window.location.assign('/login')
    }
  }, [])

  const value = useMemo<TenantContextValue>(() => {
    const isPlatform = context?.scope === 'platform'
    return {
      context,
      loading,
      error,
      isPlatform,
      devTenants,
      platformName: context?.platform_name ?? 'Agent运营管理平台',
      scopeLabel: isPlatform ? '产品级运营管理平台' : (context?.tenant?.name ?? '租户'),
      switchTenant,
    }
  }, [context, loading, error, devTenants, switchTenant])

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>
}

export function useTenant(): TenantContextValue {
  const value = useContext(TenantContext)
  if (!value) {
    throw new Error('useTenant 必须在 TenantProvider 内使用')
  }
  return value
}

/** 作用域加载门禁：域名无法识别时展示错误，避免后续请求全部失败。 */
export function TenantGate({ children }: { children: ReactNode }) {
  const { loading, error } = useTenant()
  if (loading) return <PageLoading />
  if (error) {
    return (
      <div className="page-loading">
        <Result status="error" title="无法访问当前站点" subTitle={error} />
      </div>
    )
  }
  return <>{children}</>
}
