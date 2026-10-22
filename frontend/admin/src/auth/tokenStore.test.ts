import { afterEach, describe, expect, it } from 'vitest'
import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  hasRefreshToken,
  setAccessToken,
  setRefreshToken,
} from './tokenStore'

afterEach(() => {
  clearSession({ broadcast: false })
  localStorage.clear()
})

describe('tokenStore', () => {
  it('清理旧版本遗留的访问令牌键', () => {
    localStorage.setItem('boxia_admin_token', 'legacy-token')
    expect(getRefreshToken()).toBeNull()
    expect(localStorage.getItem('boxia_admin_token')).toBeNull()
  })

  it('访问令牌仅保存在内存', () => {
    setAccessToken('access-1')
    expect(getAccessToken()).toBe('access-1')
    expect(localStorage.getItem('boxia_admin_access')).toBeNull()
  })

  it('刷新令牌持久化到 localStorage', () => {
    setRefreshToken('bxt_1')
    expect(getRefreshToken()).toBe('bxt_1')
    expect(hasRefreshToken()).toBe(true)
  })

  it('clearSession 同时清除访问与刷新令牌', () => {
    setAccessToken('access-1')
    setRefreshToken('bxt_1')
    clearSession({ broadcast: false })
    expect(getAccessToken()).toBeNull()
    expect(getRefreshToken()).toBeNull()
    expect(hasRefreshToken()).toBe(false)
  })
})
