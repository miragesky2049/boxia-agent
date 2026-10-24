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

/** 每次测试前把租户管理员重置为已知初始密码。租户管理员已并入 users，平台无法直接重置。 */
async function resetTenantAdminPassword(request: APIRequestContext) {
  const tenantHeaders = { 'X-Tenant-Code': TENANT_CODE }
  for (const password of [TENANT_PASSWORD, TENANT_NEW_PASSWORD]) {
    const login = await request.post('/api/v1/admin/auth/login', {
      headers: tenantHeaders,
      data: { username: TENANT_ADMIN, password },
    })
    if (!login.ok()) continue
    if (password === TENANT_PASSWORD) return

    const token = ((await login.json()) as { access_token: string }).access_token
    const changed = await request.post('/api/v1/admin/auth/password', {
      headers: { ...tenantHeaders, Authorization: `Bearer ${token}` },
      data: { current_password: password, new_password: TENANT_PASSWORD },
    })
    expect(changed.status()).toBe(204)
    return
  }
  throw new Error('无法重置租户管理员密码：尝试的密码均不可用')
}

async function loginPlatform(page: Page) {
  await page.goto('/login')
  await page.getByLabel('账号').fill(ADMIN_USERNAME)
  await page.getByLabel('密码').fill(ADMIN_PASSWORD!)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(agents|change-password)$/)
}

/** 产品级登录页通过作用域下拉框切换到租户级。 */
async function switchToTenant(page: Page) {
  await page.locator('.login-card__scope-select').click()
  await page.locator('.ant-select-item-option').filter({ hasText: TENANT_NAME }).click()
  await expect(page.locator('.login-card__scope')).toContainText(TENANT_NAME)
  // 租户级不再提供作用域下拉框
  await expect(page.getByRole('combobox')).toHaveCount(0)
}

/** 租户级切换作用域只能通过 URL 上的 tenant 参数。 */
async function openScopeByUrl(page: Page, code: string, expectedText: string) {
  await page.goto(`/login?tenant=${code}`)
  await expect(page.locator('.login-card__scope')).toContainText(expectedText)
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
  await resetTenantAdminPassword(request)

  await page.goto('/login')
  await switchToTenant(page)
  await submitLogin(page, TENANT_PASSWORD)

  if (page.url().endsWith('/change-password')) {
    await page.getByLabel('当前密码').fill(TENANT_PASSWORD)
    await page.getByLabel('新密码', { exact: true }).fill(TENANT_NEW_PASSWORD)
    await page.getByLabel('确认新密码').fill(TENANT_NEW_PASSWORD)
    await page.getByRole('button', { name: '确认修改' }).click()
    await expect(page).toHaveURL(/\/login/)

    await openScopeByUrl(page, TENANT_CODE, TENANT_NAME)
    await expect(page.getByRole('combobox')).toHaveCount(0)
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

  test('产品级平台可编辑租户名称', async ({ page, request }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const auth = { Authorization: `Bearer ${token}` }
    const editedName = `${TENANT_NAME}-改`

    await loginPlatform(page)
    await page.goto('/tenants')
    await expect(page.getByRole('row', { name: new RegExp(TENANT_CODE) })).toBeVisible()

    const row = page.getByRole('row', { name: new RegExp(TENANT_CODE) })
    try {
      await row.getByRole('button', { name: '编辑' }).click()
      const dialog = page.getByRole('dialog', { name: '编辑租户' })
      await dialog.getByLabel('租户名称').fill(editedName)
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByRole('cell', { name: editedName })).toBeVisible()
    } finally {
      await request.patch(`/api/v1/admin/tenants/${tenantId}`, {
        headers: auth,
        data: { name: TENANT_NAME },
      })
    }
  })

  test('本地子域名直接进入租户作用域', async ({ page, request }) => {
    const token = await adminToken(request)
    await ensureTenant(request, token)

    await page.goto(`http://${TENANT_CODE}.localhost:5173/login`)
    await expect(page.locator('.login-card__scope')).toContainText(TENANT_NAME)
    await expect(page.locator('.login-card__hint')).toContainText('按域名解析作用域')
    // 子域名模式不再提供作用域下拉框
    await expect(page.getByRole('combobox')).toHaveCount(0)
  })

  test('租户级作用域只能通过 URL 参数切换', async ({ page, request }) => {
    const token = await adminToken(request)
    await ensureTenant(request, token)

    await page.goto('/login')
    // 产品级登录页提供作用域下拉框
    await expect(page.getByRole('combobox')).toHaveCount(1)
    await switchToTenant(page)

    await openScopeByUrl(page, 'platform', '产品级')
    await expect(page.getByRole('combobox')).toHaveCount(1)
  })

  test('本地切换租户后，租户管理员只能进入租户作用域', async ({ page, request }) => {
    const token = await adminToken(request)
    await loginTenant(page, request, token)

    await expect(page.locator('.admin-sider__title')).toContainText(TENANT_NAME)
    await expect(page.getByRole('menuitem', { name: '租户管理' })).toHaveCount(0)

    await page.goto('/tenants')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
  })

  test('平台智能体授权给租户后才可见', async ({ page, request }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const name = `平台授权智能体 ${Date.now()}`

    const created = await request.post('/api/v1/admin/agents', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name, description: '产品级维护', is_enabled: true, config: {} },
    })
    expect(created.status()).toBe(201)
    const agentId = ((await created.json()) as { id: number }).id

    try {
      await loginTenant(page, request, token)
      await page.goto('/agents')
      const search = page.getByPlaceholder('搜索智能体名称或描述')
      await search.fill(name)
      await search.press('Enter')
      await expect(page.getByRole('row', { name: new RegExp(name) })).toHaveCount(0)

      const grant = await request.put(
        `/api/v1/admin/grants?resource_type=agent&resource_id=${agentId}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          data: { grants: [{ tenant_id: tenantId, role_id: null }] },
        },
      )
      expect(grant.ok()).toBeTruthy()

      await search.fill(name)
      await search.press('Enter')
      const row = page.getByRole('row', { name: new RegExp(name) })
      await expect(row).toBeVisible()
      await expect(row.getByText('平台级')).toBeVisible()
      await expect(row.getByText('只读')).toBeVisible()
      await expect(row.getByRole('button', { name: /删\s*除/ })).toHaveCount(0)
    } finally {
      await request.delete(`/api/v1/admin/agents/${agentId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }
  })

  test('租户管理员可管理角色与最终用户', async ({ page, request }) => {
    const token = await adminToken(request)
    await loginTenant(page, request, token)

    const suffix = Date.now()
    const roleName = `E2E 角色 ${suffix}`
    await page.getByRole('menuitem', { name: '角色管理' }).click()
    await expect(page.getByRole('heading', { name: '角色管理' })).toBeVisible()

    await page.getByRole('button', { name: '新建角色' }).click()
    const dialog = page.getByRole('dialog', { name: '新建角色' })
    await dialog.getByLabel('角色编码').fill(`e2e-role-${suffix}`)
    await dialog.getByLabel('角色名称').fill(roleName)
    await dialog.getByRole('button', { name: '保存' }).click()
    await expect(page.getByText('角色已创建')).toBeVisible()

    const row = page.getByRole('row', { name: new RegExp(roleName) })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /删\s*除/ }).click()
    await page
      .locator('.ant-popconfirm')
      .getByRole('button', { name: /删\s*除/ })
      .click()
    await expect(page.getByText('角色已删除')).toBeVisible()

    await page.getByRole('menuitem', { name: '用户管理' }).click()
    await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
    await expect(page.getByRole('button', { name: '新建用户' })).toBeVisible()
  })
})
