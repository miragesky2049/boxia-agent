import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import type { AdminRole } from '../api/types'
import { useTenant } from '../tenant/TenantContext'
import { useAuth } from './AuthContext'

interface RequireRoleProps {
  role: AdminRole
  /** 仅产品级平台可访问（如租户管理）。 */
  platformOnly?: boolean
  children: ReactNode
}

export default function RequireRole({ role, platformOnly = false, children }: RequireRoleProps) {
  const { user, systemRole, loading } = useAuth()
  const { isPlatform } = useTenant()

  if (loading) return <PageLoading />
  if (!user || systemRole !== role) return <Navigate to="/404" replace />
  if (platformOnly && !isPlatform) return <Navigate to="/404" replace />

  return <>{children}</>
}
