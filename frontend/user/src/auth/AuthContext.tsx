import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { fetchMe, login as loginApi, logout as logoutApi } from '../api/auth'
import { refreshSession } from '../api/client'
import type { UserProfile } from '../api/types'
import {
  clearSession,
  hasRefreshToken,
  onSessionCleared,
  setAccessToken,
  setRefreshToken,
} from './tokenStore'

interface AuthContextValue {
  user: UserProfile | null
  loading: boolean
  signIn: (username: string, password: string) => Promise<UserProfile>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(() => hasRefreshToken())

  useEffect(() => {
    let active = true

    async function restore() {
      if (!hasRefreshToken()) return
      const result = await refreshSession()
      if (!active) return
      if (result !== 'ok') {
        clearSession()
        return
      }
      try {
        const profile = await fetchMe()
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
    try {
      const profile = await fetchMe()
      setUser(profile)
      return profile
    } catch (error) {
      clearSession()
      setUser(null)
      throw error
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
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, signIn, signOut }),
    [user, loading, signIn, signOut],
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
