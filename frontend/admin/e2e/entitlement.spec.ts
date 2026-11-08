import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

// §5.3 权益流 E2E：开通/审核/角色授权/用户可见/跨作用域。
// 场景 4 用户端可见性在 e2e 走用户站点 API（:8001）断言（用户门户独立前端不在 admin e2e 范围）。
// 浏览器能解析 *.localhost 通配域，但 Playwright 的 Node 请求上下文不能（ENOTFOUND），
// 因此用户站点请求走回环地址 + X-Tenant-Code 头解析租户作用域（ALLOW_TENANT_HEADER 本地已开启）。

const ADMIN_USERNAME = process.env.E2E_USERNAME ?? 'admin'
const ADMIN_PASSWORD = process.env.E2E_PASSWORD
const TENANT_CODE = process.env.E2E_TENANT_CODE ?? 'e2etenant'
const TENANT_NAME = 'E2E 租户'
const TENANT_ADMIN = `${TENANT_CODE}-admin`
const TENANT_PASSWORD = 'Tenant-Trial-8891'
const USER_SITE_BASE = process.env.E2E_USER_BASE ?? 'http://127.0.0.1:8001'

if (!ADMIN_PASSWORD) {
  throw new Error('缺少 E2E_PASSWORD 环境变量，请先设置 E2E 管理员密码')
}

test.setTimeout(90_000)

const RESOURCE_CONFIG = JSON.stringify({ url: 'https://example.com/api', method: 'GET' })

async function adminToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/admin/auth/login', {
    data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  })
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function ensureTenant(request: APIRequestContext, token: string): Promise<string> {
  const auth = { Authorization: `Bearer ${token}` }
  const list = await request.get('/api/v1/admin/tenants?page_size=100', { headers: auth })
  const body = (await list.json()) as { items: { id: string; code: string }[] }
  const existing = body.items.find((item) => item.code === TENANT_CODE)
  if (existing) return existing.id
  const created = await request.post('/api/v1/admin/tenants', {
    headers: auth,
    data: {
      code: TENANT_CODE,
      name: TENANT_NAME,
      admin_username: TENANT_ADMIN,
      admin_password: TENANT_PASSWORD,
      admin_display_name: 'E2E 租户管理员',
    },
  })
  expect(created.status()).toBe(201)
  return ((await created.json()) as { id: string }).id
}

async function tenantAdminToken(request: APIRequestContext): Promise<string> {
  const tenantHeaders = { 'X-Tenant-Code': TENANT_CODE }
  const attempts: string[] = []
  for (const password of [TENANT_PASSWORD, 'Tenant-Trial-9922']) {
    const login = await request.post('/api/v1/admin/auth/login', {
      headers: tenantHeaders,
      data: { username: TENANT_ADMIN, password },
    })
    if (!login.ok()) {
      attempts.push(`${password}:${login.status()}`)
      continue
    }
    const token = ((await login.json()) as { access_token: string }).access_token
    if (password === TENANT_PASSWORD) return token
    const changed = await request.post('/api/v1/admin/auth/password', {
      headers: { ...tenantHeaders, Authorization: `Bearer ${token}` },
      data: { current_password: password, new_password: TENANT_PASSWORD },
    })
    expect(changed.status(), await changed.text()).toBe(204)
    return (
      await (
        await request.post('/api/v1/admin/auth/login', {
          headers: tenantHeaders,
          data: { username: TENANT_ADMIN, password: TENANT_PASSWORD },
        })
      ).json()
    ).access_token
  }
  throw new Error(
    `无法获取租户管理员令牌：尝试的密码均不可用（可能已触发登录锁定） [${attempts.join(', ')}]`,
  )
}

async function createPlatformSkill(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const created = await request.post('/api/v1/admin/resources', {
    headers: { Authorization: `Bearer ${token}` },
    data: { type: 'skill', name, config: JSON.parse(RESOURCE_CONFIG) },
  })
  expect(created.status()).toBe(201)
  return ((await created.json()) as { resource_id: string }).resource_id
}

async function batchEntitlement(
  request: APIRequestContext,
  token: string,
  tenantId: string,
  mode: 'grant' | 'revoke',
  items: { object_type: string; object_id: string }[],
): Promise<void> {
  const response = await request.post('/api/v1/admin/entitlements/batch', {
    headers: { Authorization: `Bearer ${token}` },
    data: { tenant_id: tenantId, mode, items },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
}

async function loginPlatform(page: Page) {
  // 租户 code 会跨退出登录残留在 localStorage，显式用 ?tenant=platform 回产品级作用域
  await page.goto('/login?tenant=platform')
  await page.getByLabel('账号').fill(ADMIN_USERNAME)
  await page.getByLabel('密码').fill(ADMIN_PASSWORD!)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(apps|change-password)$/)
}

async function loginTenant(page: Page, request: APIRequestContext, token: string) {
  await ensureTenant(request, token)
  await tenantAdminToken(request)
  await page.goto(`/login?tenant=${TENANT_CODE}`)
  await expect(page.locator('.login-card__scope')).toContainText(TENANT_NAME)
  await page.getByLabel('账号').fill(TENANT_ADMIN)
  await page.getByLabel('密码').fill(TENANT_PASSWORD)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(apps|change-password)$/)
  if (page.url().endsWith('/change-password')) {
    await page.getByLabel('当前密码').fill(TENANT_PASSWORD)
    await page.getByLabel('新密码', { exact: true }).fill(TENANT_PASSWORD)
    await page.getByLabel('确认新密码').fill(TENANT_PASSWORD)
    await page.getByRole('button', { name: '确认修改' }).click()
    await expect(page).toHaveURL(/\/login/)
    await page.goto(`/login?tenant=${TENANT_CODE}`)
    await page.getByLabel('账号').fill(TENANT_ADMIN)
    await page.getByLabel('密码').fill(TENANT_PASSWORD)
    await page.getByRole('button', { name: /登\s*录/ }).click()
  }
  await expect(page).toHaveURL(/\/apps$/)
}

async function selectTenantOnEntitlementsPage(page: Page) {
  await page.locator('.ant-select-selector', { hasText: '选择租户' }).click()
  await page
    .locator('.ant-select-item-option')
    .filter({ hasText: `${TENANT_NAME}（${TENANT_CODE}）` })
    .first()
    .click()
}

test.describe('权益流 E2E（§5.3）', () => {
  test('场景1：平台批量开通技能，预览确认后列表出现权益', async ({ page, request }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const suffix = Date.now()
    const name = `E2E权益技能${suffix}`
    const skillId = await createPlatformSkill(request, token, name)

    try {
      await loginPlatform(page)
      await page.goto('/entitlements')
      await selectTenantOnEntitlementsPage(page)

      await page.getByRole('button', { name: '批量开通' }).click()
      const picker = page.getByRole('dialog', { name: '选择要开通的对象' })
      await expect(picker.getByRole('button', { name: '下一步：预览' })).toBeDisabled()
      await picker.locator('.ant-select-selector').first().click()
      await page.locator('.ant-select-item-option').filter({ hasText: '技能' }).first().click()
      const skillRow = picker.getByRole('row', { name: new RegExp(name) })
      await expect(skillRow).toBeVisible()
      await skillRow.getByRole('checkbox').click()
      await picker.getByRole('button', { name: '下一步：预览' }).click()

      const preview = page.getByRole('dialog', { name: '开通预览' })
      await expect(preview.getByText(name)).toBeVisible()
      await preview.getByLabel('开通事由').fill('e2e 批量开通测试')
      await preview.getByRole('button', { name: '确认执行' }).click()
      await expect(page.getByText('已更新 1 项')).toBeVisible()

      const tableRow = page.getByRole('row', { name: new RegExp(name) })
      await expect(tableRow).toBeVisible()
      await expect(tableRow).toContainText('生效中')
    } finally {
      await batchEntitlement(request, token, tenantId, 'revoke', [
        { object_type: 'skill', object_id: skillId },
      ])
      await request.delete(`/api/v1/admin/resources/${skillId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }
  })

  test('场景2：平台审核通过租户自建资源', async ({ page, request }) => {
    const token = await adminToken(request)
    await ensureTenant(request, token)
    const tenantToken = await tenantAdminToken(request)
    const name = `E2E自建待审技能${Date.now()}`

    const created = await request.post('/api/v1/admin/my-resources', {
      headers: { Authorization: `Bearer ${tenantToken}`, 'X-Tenant-Code': TENANT_CODE },
      data: { type: 'skill', name, config: JSON.parse(RESOURCE_CONFIG) },
    })
    expect(created.status()).toBe(201)
    const resourceId = ((await created.json()) as { resource_id: string }).resource_id

    try {
      await loginPlatform(page)
      await page.goto('/resources')
      await page.locator('.ant-select-selector', { hasText: '审核状态' }).click()
      await page.locator('.ant-select-item-option').filter({ hasText: '待审核' }).first().click()

      const row = page.getByRole('row', { name: new RegExp(name) })
      await expect(row).toBeVisible()
      await expect(row).toContainText('自建')
      await row.getByRole('button', { name: /审\s*核/ }).click()

      const dialog = page.getByRole('dialog', { name: `审核资源：${name}` })
      await dialog.getByPlaceholder('审核备注（可选，驳回时建议写明原因）').fill('e2e 审核通过')
      await dialog.getByRole('button', { name: /通\s*过/ }).click()
      await expect(page.getByText('已通过审核')).toBeVisible()

      // 列表仍按"待审核"过滤，通过后该行会从结果消失：切到"已通过"再断言状态
      await page.locator('.ant-select-selector', { hasText: '待审核' }).click()
      await page.locator('.ant-select-item-option').filter({ hasText: '已通过' }).first().click()
      const reviewedRow = page.getByRole('row', { name: new RegExp(name) })
      await expect(reviewedRow).toContainText('已通过')
    } finally {
      await request.delete(`/api/v1/admin/resources/${resourceId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }
  })

  test('场景3：租户角色详情数据授权只含已开通资源，批量授权成功', async ({ page, request }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const suffix = Date.now()
    const grantedName = `E2E已开技能${suffix}`
    const notGrantedName = `E2E未开技能${suffix}`
    const grantedId = await createPlatformSkill(request, token, grantedName)
    const notGrantedId = await createPlatformSkill(request, token, notGrantedName)
    await batchEntitlement(request, token, tenantId, 'grant', [
      { object_type: 'skill', object_id: grantedId },
    ])

    try {
      await loginTenant(page, request, token)
      // 0073：角色授权页并入角色详情，入口为角色列表「授权」→ 数据授权页签
      await page.goto('/roles')
      await page
        .getByRole('row', { name: /\badmin\b/ })
        .getByRole('button', { name: '授权' })
        .click()
      await page.getByRole('tab', { name: '数据授权' }).click()
      await page.getByRole('menuitem', { name: /^技能（/ }).click()
      const search = page.getByPlaceholder('搜索名称或描述')
      await search.fill('E2E')
      await search.press('Enter')

      const grantedRow = page.getByRole('row', { name: new RegExp(grantedName) })
      await expect(grantedRow).toBeVisible()
      await expect(grantedRow).toContainText('未授权')
      await expect(page.getByRole('row', { name: new RegExp(notGrantedName) })).toHaveCount(0)

      await grantedRow.getByRole('checkbox').click()
      await page.getByRole('button', { name: /批量授权（1）/ }).click()
      await expect(page.getByText('已授权 1 项')).toBeVisible()
      await expect(page.getByRole('row', { name: new RegExp(grantedName) })).toContainText('已授权')
    } finally {
      await batchEntitlement(request, token, tenantId, 'revoke', [
        { object_type: 'skill', object_id: grantedId },
      ])
      await request.delete(`/api/v1/admin/resources/${grantedId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      await request.delete(`/api/v1/admin/resources/${notGrantedId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }
  })

  test('场景4：用户端仅可见已开通应用（用户站点 API 断言）', async ({ request }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const suffix = Date.now()
    const grantedName = `E2E用户可见应用${suffix}`
    const hiddenName = `E2E用户不可见应用${suffix}`

    const createdA = await request.post('/api/v1/admin/apps', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name: grantedName, description: '已开通' },
    })
    expect(createdA.status()).toBe(201)
    const appA = ((await createdA.json()) as { application_id: string }).application_id
    const createdB = await request.post('/api/v1/admin/apps', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name: hiddenName, description: '未开通' },
    })
    expect(createdB.status()).toBe(201)

    const tenantToken = await tenantAdminToken(request)
    const roles = (await (
      await request.get('/api/v1/admin/roles', {
        headers: { Authorization: `Bearer ${tenantToken}`, 'X-Tenant-Code': TENANT_CODE },
      })
    ).json()) as { id: string; code: string }[]
    const viewer = roles.find((item) => item.code === 'viewer')
    expect(viewer).toBeTruthy()
    const username = `e2e_user_${suffix}`
    const userPassword = 'User-View-2345'
    const userCreated = await request.post('/api/v1/admin/users', {
      headers: { Authorization: `Bearer ${tenantToken}`, 'X-Tenant-Code': TENANT_CODE },
      data: {
        username,
        password: userPassword,
        display_name: 'E2E 最终用户',
        role_ids: [viewer!.id],
      },
    })
    expect(userCreated.status()).toBe(201)
    const userId = ((await userCreated.json()) as { id: string }).id

    try {
      await batchEntitlement(request, token, tenantId, 'grant', [
        { object_type: 'app', object_id: appA },
      ])

      const login = await request.post(`${USER_SITE_BASE}/api/v1/user/auth/login`, {
        headers: { 'X-Tenant-Code': TENANT_CODE },
        data: { username, password: userPassword },
      })
      expect(login.ok(), await login.text()).toBeTruthy()
      const accessToken = ((await login.json()) as { access_token: string }).access_token

      const agents = (await (
        await request.get(`${USER_SITE_BASE}/api/v1/user/agents?page=1&page_size=100`, {
          headers: { Authorization: `Bearer ${accessToken}`, 'X-Tenant-Code': TENANT_CODE },
        })
      ).json()) as { items: { id: string; name: string }[] }
      const names = agents.items.map((item) => item.name)
      expect(names).toContain(grantedName)
      expect(names).not.toContain(hiddenName)
    } finally {
      await batchEntitlement(request, token, tenantId, 'revoke', [
        { object_type: 'app', object_id: appA },
      ])
      await request.delete(`/api/v1/admin/users/${userId}`, {
        headers: { Authorization: `Bearer ${tenantToken}`, 'X-Tenant-Code': TENANT_CODE },
      })
    }
  })

  test('场景5：跨作用域互斥，租户访问开通页 404，旧角色授权路由下线后各作用域均 404', async ({
    page,
    request,
  }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const tenantToken = await tenantAdminToken(request)

    // 必须带 X-Tenant-Code 才能解析到租户作用域；缺头时按平台作用域校验令牌 → 401
    const forbidden = await request.get(`/api/v1/admin/entitlements/tenants/${tenantId}`, {
      headers: { Authorization: `Bearer ${tenantToken}`, 'X-Tenant-Code': TENANT_CODE },
    })
    expect(forbidden.status(), await forbidden.text()).toBe(403)

    await loginTenant(page, request, token)
    await page.goto('/entitlements')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()

    // 0073：旧角色授权路由已从任何作用域下线
    await page.goto('/role-access')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()

    // 404 页不套后台布局（无用户菜单），先回 /apps 再退出；
    // 已登录状态下 goto('/login') 会被会话重定向到 /apps，必须先走 UI 退出登录
    await page.goto('/apps')
    await page.locator('.admin-header__user').click()
    await page.getByRole('menuitem', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login/)

    await loginPlatform(page)
    await page.goto('/role-access')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
  })
})
