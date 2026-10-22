import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

const ADMIN_USERNAME = process.env.E2E_USERNAME ?? 'admin'
const ADMIN_PASSWORD = process.env.E2E_PASSWORD
const TENANT_CODE = process.env.E2E_TENANT_CODE ?? 'e2etenant'
const TENANT_NAME = 'E2E 租户'
const TENANT_ADMIN = `${TENANT_CODE}-admin`
const TENANT_PASSWORD = 'Tenant-Trial-8891'
const TENANT_NEW_PASSWORD = 'Tenant-Trial-9922'

if (!ADMIN_PASSWORD) {
  throw new Error('缺少 E2E_PASSWORD 环境变量，请先设置 E2E 管理员密码')
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/admin/auth/login', {
    data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  })
  expect(response.ok()).toBeTruthy()
  return ((await response.json()) as { access_token: string }).access_token
}

async function ensureTenant(request: APIRequestContext, token: string): Promise<number> {
  const auth = { Authorization: `Bearer ${token}` }
  const list = await request.get('/api/v1/admin/tenants?page_size=100', { headers: auth })
  const body = (await list.json()) as { items: { id: number; code: string }[] }
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
  return ((await created.json()) as { id: number }).id
}

/** 每次测试前把租户管理员重置为已知初始密码，并保持首登改密标记。 */
async function resetTenantAdminPassword(request: APIRequestContext, token: string) {
  const auth = { Authorization: `Bearer ${token}` }
  const list = await request.get(
    `/api/v1/admin/users?all_tenants=true&page_size=100&keyword=${TENANT_ADMIN}`,
    { headers: auth },
  )
  const body = (await list.json()) as { items: { id: number; username: string }[] }
  const target = body.items.find((item) => item.username === TENANT_ADMIN)
  expect(target).toBeTruthy()
  const reset = await request.post(`/api/v1/admin/users/${target!.id}/password`, {
    headers: auth,
    data: { new_password: TENANT_PASSWORD },
  })
  expect(reset.status()).toBe(204)
}

async function loginPlatform(page: Page) {
  await page.goto('/login')
  await page.getByLabel('账号').fill(ADMIN_USERNAME)
  await page.getByLabel('密码').fill(ADMIN_PASSWORD!)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(agents|change-password)$/)
}

async function switchToTenant(page: Page) {
  await page.locator('.login-card__scope-select').click()
  await page.locator('.ant-select-item-option').filter({ hasText: TENANT_NAME }).click()
  await expect(page.locator('.login-card__scope')).toContainText(TENANT_NAME)
}

async function submitLogin(page: Page, password: string) {
  await page.getByLabel('账号').fill(TENANT_ADMIN)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(agents|change-password)$/)
}

/** 切换到租户作用域并完成登录；首登会先完成强制改密。 */
async function loginTenant(page: Page, request: APIRequestContext, token: string) {
  await ensureTenant(request, token)
  await resetTenantAdminPassword(request, token)

  await page.goto('/login')
  await switchToTenant(page)
  await submitLogin(page, TENANT_PASSWORD)

  if (page.url().endsWith('/change-password')) {
    await page.getByLabel('当前密码').fill(TENANT_PASSWORD)
    await page.getByLabel('新密码', { exact: true }).fill(TENANT_NEW_PASSWORD)
    await page.getByLabel('确认新密码').fill(TENANT_NEW_PASSWORD)
    await page.getByRole('button', { name: '确认修改' }).click()
    await expect(page).toHaveURL(/\/login/)

    await switchToTenant(page)
    await submitLogin(page, TENANT_NEW_PASSWORD)
  }
  await expect(page).toHaveURL(/\/agents$/)
}

test.describe('多租户', () => {
  test('产品级平台可管理租户', async ({ page, request }) => {
    const token = await adminToken(request)
    await ensureTenant(request, token)

    await loginPlatform(page)
    await page.goto('/tenants')
    await expect(page.getByRole('heading', { name: '租户管理' })).toBeVisible()
    await expect(page.getByRole('row', { name: new RegExp(TENANT_CODE) })).toBeVisible()
  })

  test('开发态切换租户后，租户管理员只能进入租户作用域', async ({ page, request }) => {
    const token = await adminToken(request)
    await loginTenant(page, request, token)

    await expect(page.locator('.admin-sider__title')).toContainText(TENANT_NAME)
    await expect(page.getByRole('menuitem', { name: '租户管理' })).toHaveCount(0)

    await page.goto('/tenants')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
  })

  test('租户内产品级资源只读', async ({ page, request }) => {
    const token = await adminToken(request)
    await ensureTenant(request, token)

    const name = `平台共享技能 ${Date.now()}`
    const created = await request.post('/api/v1/admin/skills', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name, description: '产品级维护', is_enabled: true, content: '', config: {} },
    })
    expect(created.status()).toBe(201)

    await loginTenant(page, request, token)

    await page.goto('/skills')
    await page.getByPlaceholder('搜索名称或描述').fill(name)
    await page.getByPlaceholder('搜索名称或描述').press('Enter')

    const row = page.getByRole('row', { name: new RegExp(name) })
    await expect(row).toBeVisible()
    await expect(row.getByText('平台级')).toBeVisible()
    await expect(row.getByText('产品级资源只读')).toBeVisible()
    await expect(row.getByRole('button', { name: /删\s*除/ })).toHaveCount(0)
  })
})
