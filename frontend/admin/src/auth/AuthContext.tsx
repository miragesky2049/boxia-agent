import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  changePassword as changePasswordApi,
  fetchCurrentUser,
  login as loginApi,
  logout as logoutApi,
} from '../api/auth'
import { refreshSession } from '../api/client'
import type { AdminUser } from '../api/types'
import {
  clearSession,
  hasRefreshToken,
  onSessionCleared,
  setAccessToken,
  setRefreshToken,
} from './tokenStore'

interface AuthContextValue {
  user: AdminUser | null
  loading: boolean
  mustChangePassword: boolean
  canWrite: boolean
  isSuperAdmin: boolean
  signIn: (username: string, password: string) => Promise<AdminUser>
  signOut: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null)
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
        const profile = await fetchCurrentUser()
        if (active) setUser(profile)
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

  useEffect(() => onSessionCleared(() => setUser(null)), [])

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await loginApi(username, password)
    setAccessToken(result.access_token)
    setRefreshToken(result.refresh_token)
    setUser(result.user)
    return result.user
  }, [])

  const signOut = useCallback(async () => {
    try {
      await logoutApi()
    } catch {
      // 后端不可达时仍需完成本地登出
    }
    clearSession()
    setUser(null)
  }, [])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    await changePasswordApi(currentPassword, newPassword)
    clearSession()
    setUser(null)
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      mustChangePassword: user?.must_change_password ?? false,
      canWrite: user?.role !== 'viewer',
      isSuperAdmin: user?.role === 'superadmin',
      signIn,
      signOut,
      changePassword,
    }),
    [user, loading, signIn, signOut, changePassword],
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
