import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import { useTenant } from '../tenant/TenantContext'
import { useAuth } from './AuthContext'

interface RequirePermissionProps {
  /** 进入页面所需的权限编码（通常为 page:*）。 */
  permission: string
  /** 仅产品级平台可访问（如租户管理）。 */
  platformOnly?: boolean
  /** 仅租户作用域可访问（如角色授权、用户授权）。 */
  tenantOnly?: boolean
  children: ReactNode
}

export default function RequirePermission({
  permission,
  platformOnly = false,
  tenantOnly = false,
  children,
}: RequirePermissionProps) {
  const { user, loading, hasPermission } = useAuth()
  const { isPlatform } = useTenant()

  if (loading) return <PageLoading />
  if (!user || !hasPermission(permission)) return <Navigate to="/404" replace />
  if (platformOnly && !isPlatform) return <Navigate to="/404" replace />
  if (tenantOnly && isPlatform) return <Navigate to="/404" replace />

  return <>{children}</>
}
