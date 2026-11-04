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

/** 每次测试前把租户管理员重置为已知初始密码。租户管理员已并入 users，平台无法直接重置。 */
async function resetTenantAdminPassword(request: APIRequestContext) {
  const tenantHeaders = { 'X-Tenant-Code': TENANT_CODE }
  const attempts: string[] = []
  for (const password of [TENANT_PASSWORD, TENANT_NEW_PASSWORD]) {
    const login = await request.post('/api/v1/admin/auth/login', {
      headers: tenantHeaders,
      data: { username: TENANT_ADMIN, password },
    })
    if (!login.ok()) {
      attempts.push(`${password}:${login.status()}`)
      continue
    }
    if (password === TENANT_PASSWORD) return

    const token = ((await login.json()) as { access_token: string }).access_token
    const changed = await request.post('/api/v1/admin/auth/password', {
      headers: { ...tenantHeaders, Authorization: `Bearer ${token}` },
      data: { current_password: password, new_password: TENANT_PASSWORD },
    })
    expect(changed.status(), await changed.text()).toBe(204)
    return
  }
  throw new Error(`无法重置租户管理员密码：尝试的密码均不可用（可能已触发登录锁定） [${attempts.join(', ')}]`)
}

async function loginPlatform(page: Page) {
  await page.goto('/login')
  await page.getByLabel('账号').fill(ADMIN_USERNAME)
  await page.getByLabel('密码').fill(ADMIN_PASSWORD!)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(apps|change-password)$/)
}

/** 本地回环为 header 模式：通过 URL ?tenant= 切到租户作用域；租户级不再提供作用域下拉框。 */
async function openTenantScope(page: Page, code = TENANT_CODE, expectedText = TENANT_NAME) {
  await page.goto(`/login?tenant=${code}`)
  await expect(page.locator('.login-card__scope')).toContainText(expectedText)
  // 作用域下拉只在产品级出现；切回 platform 时下拉合法存在，由调用方断言数量
  if (code !== 'platform') {
    await expect(page.getByRole('combobox')).toHaveCount(0)
  }
}

async function submitLogin(page: Page, password: string) {
  await page.getByLabel('账号').fill(TENANT_ADMIN)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(apps|change-password)$/)
}

/** 切换到租户作用域并完成登录；首登会先完成强制改密。 */
async function loginTenant(page: Page, request: APIRequestContext, token: string) {
  await ensureTenant(request, token)
  await resetTenantAdminPassword(request)

  await openTenantScope(page)
  await submitLogin(page, TENANT_PASSWORD)

  if (page.url().endsWith('/change-password')) {
    await page.getByLabel('当前密码').fill(TENANT_PASSWORD)
    await page.getByLabel('新密码', { exact: true }).fill(TENANT_NEW_PASSWORD)
    await page.getByLabel('确认新密码').fill(TENANT_NEW_PASSWORD)
    await page.getByRole('button', { name: '确认修改' }).click()
    await expect(page).toHaveURL(/\/login/)

    await openTenantScope(page)
    await submitLogin(page, TENANT_NEW_PASSWORD)
  }
  await expect(page).toHaveURL(/\/apps$/)
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
      await row.getByRole('button', { name: /编\s*辑/ }).click()
      const dialog = page.getByRole('dialog', { name: '编辑租户' })
      await dialog.getByLabel('租户名称').fill(editedName)
      await dialog.getByRole('button', { name: /保\s*存/ }).click()
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
    await expect(page.getByRole('combobox')).toHaveCount(0)
  })

  test('租户级作用域只能通过 URL 参数切换', async ({ page, request }) => {
    const token = await adminToken(request)
    await ensureTenant(request, token)

    await page.goto('/login')
    // 产品级登录页在本地回环（header 模式）提供作用域下拉框
    await expect(page.getByRole('combobox')).toHaveCount(1)

    await openTenantScope(page, TENANT_CODE, TENANT_NAME)

    await openTenantScope(page, 'platform', '产品级')
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

  test('平台开通应用后租户才可见', async ({ page, request }) => {
    const token = await adminToken(request)
    const tenantId = await ensureTenant(request, token)
    const name = `平台开通应用 ${Date.now()}`

    const created = await request.post('/api/v1/admin/apps', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name, description: '产品级维护' },
    })
    expect(created.status()).toBe(201)
    const appId = ((await created.json()) as { application_id: string }).application_id

    try {
      await loginTenant(page, request, token)
      await page.goto('/apps')
      await expect(page.getByText(name)).toHaveCount(0)

      const granted = await request.post('/api/v1/admin/entitlements/batch', {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          tenant_id: tenantId,
          mode: 'grant',
          items: [{ object_type: 'app', object_id: appId }],
        },
      })
      expect(granted.ok()).toBeTruthy()

      await page.reload()
      const card = page.locator('.ant-card', { hasText: name })
      await expect(card).toBeVisible()
      await expect(card).toContainText('已开通')
    } finally {
      // 应用无物理删除端点：回收权益即可让租户侧不可见
      await request.post('/api/v1/admin/entitlements/batch', {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          tenant_id: tenantId,
          mode: 'revoke',
          items: [{ object_type: 'app', object_id: appId }],
        },
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
    await dialog.getByRole('button', { name: /保\s*存/ }).click()
    await expect(page.getByText('角色已创建')).toBeVisible()

    const row = page.getByRole('row', { name: new RegExp(roleName) })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /删\s*除/ }).click()
    await page.locator('.ant-popconfirm').locator('.ant-btn-primary').click()
    await expect(page.getByText('角色已删除')).toBeVisible()

    await page.getByRole('menuitem', { name: '用户管理' }).click()
    await expect(page.getByText('用户管理').first()).toBeVisible()
    await expect(page.getByRole('button', { name: '新建用户' })).toBeVisible()
  })
})
