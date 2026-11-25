import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

const ADMIN_USERNAME = process.env.E2E_USERNAME ?? 'admin'
const ADMIN_PASSWORD = process.env.E2E_PASSWORD

if (!ADMIN_PASSWORD) {
  throw new Error('缺少 E2E_PASSWORD 环境变量，请先设置 E2E 管理员密码')
}
const VIEWER_USERNAME = process.env.E2E_VIEWER_USERNAME ?? 'e2e_viewer'
const VIEWER_INITIAL_PASSWORD = 'Portal-Read-1234'

async function login(
  page: Page,
  username = ADMIN_USERNAME,
  password = ADMIN_PASSWORD!,
  expectSuccess = true,
) {
  await page.goto('/login')
  await page.getByLabel('账号').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  if (expectSuccess) {
    await page.waitForURL(/\/(apps|change-password)$/)
  }
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const response = await request.post('/api/v1/admin/auth/login', {
    data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  })
  expect(response.ok()).toBeTruthy()
  const body = (await response.json()) as { access_token: string }
  return body.access_token
}

async function ensureViewer(request: APIRequestContext, token: string): Promise<string> {
  const auth = { Authorization: `Bearer ${token}` }
  const listResponse = await request.get(`/api/v1/admin/admin-users?keyword=${VIEWER_USERNAME}`, {
    headers: auth,
  })
  const list = (await listResponse.json()) as { items: { id: string; username: string }[] }
  const existing = list.items.find((item) => item.username === VIEWER_USERNAME)

  if (!existing) {
    const roles = (await (await request.get('/api/v1/admin/roles', { headers: auth })).json()) as {
      id: string
      code: string
    }[]
    const viewer = roles.find((item) => item.code === 'viewer')
    expect(viewer).toBeTruthy()
    const created = await request.post('/api/v1/admin/admin-users', {
      headers: auth,
      data: {
        username: VIEWER_USERNAME,
        display_name: 'E2E 只读用户',
        password: VIEWER_INITIAL_PASSWORD,
        role_id: viewer!.id,
      },
    })
    expect(created.status()).toBe(201)
    return ((await created.json()) as { id: string }).id
  }

  const reset = await request.post(`/api/v1/admin/admin-users/${existing.id}/password`, {
    headers: auth,
    data: { new_password: VIEWER_INITIAL_PASSWORD },
  })
  expect(reset.status()).toBe(204)
  return existing.id
}

test.describe('认证流程', () => {
  test('错误密码给出提示', async ({ page }) => {
    await login(page, ADMIN_USERNAME, 'wrong-password-123', false)
    await expect(page.getByText('用户名或密码错误')).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('登录后刷新页面保持会话', async ({ page }) => {
    await login(page)
    await expect(page).toHaveURL(/\/apps$/)
    await expect(page.getByRole('heading', { name: '产品级应用' })).toBeVisible()

    await page.reload()
    await expect(page).toHaveURL(/\/apps$/)
    await expect(page.getByRole('heading', { name: '产品级应用' })).toBeVisible()
  })

  test('退出登录后受保护页面跳转登录', async ({ page }) => {
    await login(page)
    await page.locator('.admin-header__user').click()
    await page.getByRole('menuitem', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login/)

    await page.goto('/apps')
    await expect(page).toHaveURL(/\/login\?next=%2Fapps/)
  })
})

test.describe('资源与应用', () => {
  test('技能在资源管理页新建、编辑与删除', async ({ page }) => {
    const suffix = Date.now()
    const name = `E2E 技能 ${suffix}`
    const updatedName = `${name} 已更新`

    await login(page)
    await page.goto('/resources')
    await expect(page.getByRole('heading', { name: '资源管理' })).toBeVisible()
    await page.getByRole('tab', { name: '技能', exact: true }).click()

    await page.getByRole('button', { name: '新建资源' }).click()
    const drawer = page.locator('.ant-drawer-content')
    await expect(drawer).toBeVisible()
    await drawer.getByLabel('名称').fill(name)
    // antd Select 的可点击区域是 .ant-select-selector，search input 会被选中项遮挡
    await drawer.locator('.ant-select-selector').click()
    await page.locator('.ant-select-item-option').filter({ hasText: '技能' }).first().click()
    await drawer.getByRole('button', { name: /保\s*存/ }).click()
    await expect(page.getByText('已创建')).toBeVisible()

    const row = page.getByRole('row', { name: new RegExp(name) })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /编\s*辑/ }).click()
    await drawer.getByLabel('名称').fill(updatedName)
    await drawer.getByRole('button', { name: /保\s*存/ }).click()
    await expect(page.getByText('已保存')).toBeVisible()
    await expect(page.getByRole('row', { name: new RegExp(updatedName) })).toBeVisible()

    const updatedRow = page.getByRole('row', { name: new RegExp(updatedName) })
    await updatedRow.getByRole('button', { name: /删\s*除/ }).click()
    await page.locator('.ant-popconfirm').locator('.ant-btn-primary').click()
    await expect(page.getByText('已删除')).toBeVisible()
    await expect(page.getByRole('row', { name: new RegExp(updatedName) })).toHaveCount(0)
  })

  test('应用创建后详情可回显', async ({ page }) => {
    const name = `E2E 应用 ${Date.now()}`

    await login(page)
    await page.goto('/apps')
    await page.getByRole('button', { name: '新建应用' }).click()
    const dialog = page.getByRole('dialog', { name: '新建应用' })
    await dialog.getByPlaceholder('给应用起个名字，便于识别').fill(name)
    await dialog.getByPlaceholder('简单描述应用的用途（选填）').fill('Playwright 自动化创建')
    await dialog.getByRole('button', { name: /^创\s*建$/ }).click()

    const row = page.getByRole('row', { name: new RegExp(name) })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: /详\s*情/ }).click()
    await expect(page.getByText(`应用详情：${name}`)).toBeVisible()
  })

  test('未知路径展示 404 页面', async ({ page }) => {
    await login(page)
    await page.goto('/not-exists')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
    await expect(page.getByRole('button', { name: '返回智能体管理' })).toBeVisible()
  })
})

// 0071 起内置 viewer 不再下发 system:console:access，登录管理端直接被拒；
// 强制改密流程改由「仅有控制台+应用页访问权」的自定义角色账号验证。
const RO_ROLE_CODE = 'e2e-console-ro'
const RO_ROLE_NAME = 'E2E 控制台只读'
const RO_USERNAME = process.env.E2E_RO_USERNAME ?? 'e2e_ro_console'
const RO_INITIAL_PASSWORD = 'Portal-Ro-1234'
const RO_NEW_PASSWORD = 'Portal-Ro-5678'

/** 幂等准备自定义角色：控制台访问 + 应用页，不含任何 button 权限；每次覆盖权限避免漂移。 */
async function ensureConsoleReadOnlyRole(
  request: APIRequestContext,
  token: string,
): Promise<string> {
  const auth = { Authorization: `Bearer ${token}` }
  const roles = (await (await request.get('/api/v1/admin/roles', { headers: auth })).json()) as {
    id: string
    code: string
  }[]
  const existing = roles.find((item) => item.code === RO_ROLE_CODE)
  const roleId = existing
    ? existing.id
    : (
        (await (
          await request.post('/api/v1/admin/roles', {
            headers: auth,
            data: {
              code: RO_ROLE_CODE,
              name: RO_ROLE_NAME,
              description: 'E2E：可进控制台但无写操作权限',
            },
          })
        ).json()) as { id: string }
      ).id
  const put = await request.put(`/api/v1/admin/roles/${roleId}/permissions`, {
    headers: auth,
    data: { codes: ['system:console:access', 'menu:apps', 'page:apps'] },
  })
  expect(put.status(), await put.text()).toBeLessThan(400)
  return roleId
}

async function ensureReadOnlyUser(
  request: APIRequestContext,
  token: string,
  roleId: string,
): Promise<void> {
  const auth = { Authorization: `Bearer ${token}` }
  const list = (await (
    await request.get(`/api/v1/admin/admin-users?keyword=${RO_USERNAME}`, { headers: auth })
  ).json()) as { items: { id: string; username: string }[] }
  const existing = list.items.find((item) => item.username === RO_USERNAME)
  if (existing) {
    const reset = await request.post(`/api/v1/admin/admin-users/${existing.id}/password`, {
      headers: auth,
      data: { new_password: RO_INITIAL_PASSWORD },
    })
    expect(reset.status()).toBe(204)
    return
  }
  const created = await request.post('/api/v1/admin/admin-users', {
    headers: auth,
    data: {
      username: RO_USERNAME,
      display_name: 'E2E 控制台只读用户',
      password: RO_INITIAL_PASSWORD,
      role_id: roleId,
    },
  })
  expect(created.status(), await created.text()).toBe(201)
}

test.describe('改密与权限', () => {
  test('viewer 登录管理端被拒（0071 行为）', async ({ request, page }) => {
    const token = await adminToken(request)
    await ensureViewer(request, token)

    await login(page, VIEWER_USERNAME, VIEWER_INITIAL_PASSWORD, false)
    await expect(page.getByText('账号未获得管理端访问权限')).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('首次登录强制改密，未授权操作不可见', async ({ request, page }) => {
    const token = await adminToken(request)
    const roleId = await ensureConsoleReadOnlyRole(request, token)
    await ensureReadOnlyUser(request, token, roleId)

    await login(page, RO_USERNAME, RO_INITIAL_PASSWORD)
    await expect(page).toHaveURL(/\/change-password/)
    await page.getByLabel('当前密码').fill(RO_INITIAL_PASSWORD)
    await page.getByLabel('新密码', { exact: true }).fill(RO_NEW_PASSWORD)
    await page.getByLabel('确认新密码').fill(RO_NEW_PASSWORD)
    await page.getByRole('button', { name: '确认修改' }).click()
    await expect(page).toHaveURL(/\/login/)

    await login(page, RO_USERNAME, RO_NEW_PASSWORD)
    await expect(page).toHaveURL(/\/apps$/)
    await expect(page.getByRole('button', { name: '新建应用' })).toHaveCount(0)

    await page.goto('/users')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
    await page.goto('/roles')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
  })
})
