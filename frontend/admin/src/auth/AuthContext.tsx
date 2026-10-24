import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  changePassword as changePasswordApi,
  login as loginApi,
  logout as logoutApi,
} from '../api/auth'
import { refreshSession } from '../api/client'
import { fetchAdminContext } from '../api/tenant'
import type { AdminContext, AdminUser } from '../api/types'
import {
  clearSession,
  hasRefreshToken,
  onSessionCleared,
  setAccessToken,
  setRefreshToken,
} from './tokenStore'

interface AuthContextValue {
  user: AdminUser | null
  adminContext: AdminContext | null
  loading: boolean
  mustChangePassword: boolean
  roleCode: string
  roleName: string
  permissions: string[]
  menus: string[]
  hasPermission: (permission: string) => boolean
  signIn: (username: string, password: string) => Promise<AdminUser>
  signOut: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null)
  const [adminContext, setAdminContext] = useState<AdminContext | null>(null)
  const [loading, setLoading] = useState(() => hasRefreshToken())

  useEffect(() => {
    let active = true

    async function restore() {
      if (!hasRefreshToken()) return
      const result = await refreshSession()
      if (!active) return
      if (result === 'invalid') {
        clearSession()
        return
      }
      if (result === 'unavailable') {
        return
      }
      try {
        const profile = await fetchAdminContext()
        if (active) {
          setAdminContext(profile)
          setUser(profile.user)
        }
      } catch {
        if (active) clearSession()
      }
    }

    restore()
      .catch(() => undefined)
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  useEffect(
    () =>
      onSessionCleared(() => {
        setUser(null)
        setAdminContext(null)
      }),
    [],
  )

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await loginApi(username, password)
    setAccessToken(result.access_token)
    setRefreshToken(result.refresh_token)
    setUser(result.user)
    try {
      const profile = await fetchAdminContext()
      setAdminContext(profile)
      setUser(profile.user)
      return profile.user
    } catch {
      return result.user
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await logoutApi()
    } catch {
      // 后端不可达时仍需完成本地登出
    }
    clearSession()
    setUser(null)
    setAdminContext(null)
  }, [])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    await changePasswordApi(currentPassword, newPassword)
    clearSession()
    setUser(null)
    setAdminContext(null)
  }, [])

  const roleCode = adminContext?.role_code ?? user?.role_code ?? ''
  const roleName = adminContext?.role_name ?? user?.role_name ?? ''
  const permissions = adminContext?.permissions ?? []

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      adminContext,
      loading,
      mustChangePassword: user?.must_change_password ?? false,
      roleCode,
      roleName,
      permissions,
      menus: adminContext?.menus ?? [],
      hasPermission: (permission: string) => permissions.includes(permission),
      signIn,
      signOut,
      changePassword,
    }),
    [user, adminContext, loading, roleCode, roleName, permissions, signIn, signOut, changePassword],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth 必须在 AuthProvider 内使用')
  }
  return context
}
