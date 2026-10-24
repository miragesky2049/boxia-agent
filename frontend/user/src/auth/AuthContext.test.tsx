import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { UserProfile } from '../api/types'
import { AuthProvider, useAuth } from './AuthContext'
import { setRefreshToken } from './tokenStore'

const profile: UserProfile = {
  id: 7,
  username: 'alice',
  display_name: '爱丽丝',
  tenant_id: 2,
  role_id: 3,
  role_code: 'member',
  role_name: '成员',
  permissions: ['read'],
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function Probe() {
  const { user, loading } = useAuth()
  if (loading) return <div>loading</div>
  return <div>{user ? `user:${user.username}` : 'anonymous'}</div>
}

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('AuthProvider', () => {
  it('存在刷新令牌时恢复会话并回源用户信息', async () => {
    setRefreshToken('bxu_old')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/user/auth/refresh')) {
        return jsonResponse({
          access_token: 'access-new',
          token_type: 'bearer',
          expires_in: 1800,
          refresh_token: 'bxu_new',
          refresh_expires_in: 1209600,
          user: profile,
        })
      }
      if (url.endsWith('/user/me')) {
        return jsonResponse(profile)
      }
      return jsonResponse({ detail: 'not found' }, 404)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    expect(await screen.findByText('user:alice')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(localStorage.getItem('boxia_user_refresh')).toBe('bxu_new')
  })

  it('没有刷新令牌时直接进入未登录状态', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )

    expect(await screen.findByText('anonymous')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
