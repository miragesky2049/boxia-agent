import { Result } from 'antd'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { fetchPublicContext, fetchPublicTenants } from '../api/tenant'
import type { PublicContext, Tenant, TenantSwitchMode } from '../api/types'
import { clearSession } from '../auth/tokenStore'
import PageLoading from '../components/PageLoading'
import {
  PLATFORM_TENANT_CODE,
  buildTenantUrl,
  clearTenantParam,
  getTenantCode,
  getTenantParam,
  setTenantCode,
} from './scope'

interface TenantContextValue {
  context: PublicContext | null
  loading: boolean
  error: string
  isPlatform: boolean
  switchMode: TenantSwitchMode
  selectableTenants: Tenant[]
  platformName: string
  scopeLabel: string
  switchTenant: (code: string) => void
}

const TenantContext = createContext<TenantContextValue | null>(null)

export function TenantProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<PublicContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectableTenants, setSelectableTenants] = useState<Tenant[]>([])

  const load = useCallback(async (): Promise<PublicContext | null> => {
    setLoading(true)
    setError('')
    try {
      const result = await fetchPublicContext()
      setContext(result)
      // 只有产品级平台需要在页面切换作用域，租户级只展示当前租户名称
      if (result.tenant_switch_mode !== 'none' && result.scope === 'platform') {
        fetchPublicTenants()
          .then(setSelectableTenants)
          .catch(() => setSelectableTenants([]))
      } else {
        setSelectableTenants([])
      }
      return result
    } catch (err) {
      setContext(null)
      setError(err instanceof ApiError ? err.message : '无法识别当前访问域名')
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    const urlTenant = getTenantParam()

    const bootstrap = async () => {
      const result = await load()
      if (!active || urlTenant === null || result === null) return

      clearTenantParam()
      if (result.tenant_switch_mode === 'none') {
        // 部署环境由二级域名识别租户，URL 参数不生效；顺带清理本地残留的覆盖值
        setTenantCode('')
        return
      }

      if (result.tenant_switch_mode === 'host') {
        // 本地子域名模式：作用域只由域名决定，跳转到目标域名而不是复用请求头
        setTenantCode('')
        const targetUrl = buildTenantUrl(urlTenant || PLATFORM_TENANT_CODE, result)
        if (!targetUrl) return
        if (new URL(targetUrl).host !== window.location.host) {
          clearSession()
          window.location.assign(targetUrl)
        }
        return
      }

      const target = urlTenant || PLATFORM_TENANT_CODE
      if (target === (getTenantCode() || PLATFORM_TENANT_CODE)) return

      setTenantCode(urlTenant)
      // 切换作用域后旧令牌不再适用，回到登录页重新认证
      clearSession()
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
        return
      }
      await load()
    }

    void bootstrap()
    return () => {
      active = false
    }
  }, [load])

  const switchTenant = useCallback(
    (code: string) => {
      const mode = context?.tenant_switch_mode ?? 'none'
      if (!context || mode === 'none') return

      if (mode === 'host') {
        const targetUrl = buildTenantUrl(code, context)
        if (!targetUrl) return
        setTenantCode('')
        clearSession()
        if (new URL(targetUrl).host !== window.location.host) {
          window.location.assign(targetUrl)
        }
        return
      }

      if (code === (getTenantCode() || PLATFORM_TENANT_CODE)) return
      setTenantCode(code === PLATFORM_TENANT_CODE ? PLATFORM_TENANT_CODE : code)
      clearSession()
      window.location.assign('/login')
    },
    [context],
  )

  const value = useMemo<TenantContextValue>(() => {
    const isPlatform = context?.scope === 'platform'
    return {
      context,
      loading,
      error,
      isPlatform,
      switchMode: context?.tenant_switch_mode ?? 'none',
      selectableTenants,
      platformName: context?.platform_name ?? 'AI智能体运营管理平台',
      scopeLabel: isPlatform ? '产品级运营管理平台' : (context?.tenant?.name ?? '租户'),
      switchTenant,
    }
  }, [context, loading, error, selectableTenants, switchTenant])

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
