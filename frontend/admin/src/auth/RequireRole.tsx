import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import type { AdminRole } from '../api/types'
import { useAuth } from './AuthContext'

interface RequireRoleProps {
  role: AdminRole
  children: ReactNode
}

export default function RequireRole({ role, children }: RequireRoleProps) {
  const { user, loading } = useAuth()

  if (loading) return <PageLoading />
  if (!user || user.role !== role) return <Navigate to="/404" replace />

  return <>{children}</>
}
