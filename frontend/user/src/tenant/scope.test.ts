import { afterEach, describe, expect, it } from 'vitest'
import { getTenantCode, getTenantParam, isLocalHost, setTenantCode } from './scope'

afterEach(() => {
  setTenantCode('')
  window.history.replaceState({}, '', '/')
})

describe('租户作用域', () => {
  it('写入前统一转为小写并持久化', () => {
    setTenantCode('  Acme ')
    expect(getTenantCode()).toBe('acme')
    expect(localStorage.getItem('boxia.user-tenant-code')).toBe('acme')
  })

  it('清空后不再携带租户头', () => {
    setTenantCode('acme')
    setTenantCode('')
    expect(getTenantCode()).toBe('')
    expect(localStorage.getItem('boxia.user-tenant-code')).toBeNull()
  })

  it('从 URL 读取 tenant 参数', () => {
    window.history.replaceState({}, '', '/login?tenant=Acme')
    expect(getTenantParam()).toBe('acme')
  })

  it('回环地址才展示本地租户输入', () => {
    expect(isLocalHost()).toBe(true)
  })
})
