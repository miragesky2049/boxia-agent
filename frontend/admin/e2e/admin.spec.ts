import { expect, test } from '@playwright/test'
import type { APIRequestContext, Page } from '@playwright/test'

const ADMIN_USERNAME = process.env.E2E_USERNAME ?? 'admin'
const ADMIN_PASSWORD = process.env.E2E_PASSWORD

if (!ADMIN_PASSWORD) {
  throw new Error('缺少 E2E_PASSWORD 环境变量，请先设置 E2E 管理员密码')
}
const VIEWER_USERNAME = process.env.E2E_VIEWER_USERNAME ?? 'e2e_viewer'
const VIEWER_INITIAL_PASSWORD = 'Portal-Read-1234'
const VIEWER_NEW_PASSWORD = 'Portal-Read-5678'

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
    await page.waitForURL(/\/(agents|change-password)$/)
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
  const listResponse = await request.get(
    `/api/v1/admin/admin-users?keyword=${VIEWER_USERNAME}`,
    { headers: auth },
  )
  const list = (await listResponse.json()) as { items: { id: string; username: string }[] }
  const existing = list.items.find((item) => item.username === VIEWER_USERNAME)

  if (!existing) {
    const created = await request.post('/api/v1/admin/admin-users', {
      headers: auth,
      data: {
        username: VIEWER_USERNAME,
        display_name: 'E2E 只读用户',
        password: VIEWER_INITIAL_PASSWORD,
        role: 'viewer',
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

async function createAgent(
  request: APIRequestContext,
  token: string,
  name: string,
): Promise<string> {
  const created = await request.post('/api/v1/admin/agents', {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name,
      description: '由 Playwright 创建',
      is_enabled: true,
      config: {},
    },
  })
  expect(created.status()).toBe(201)
  return ((await created.json()) as { id: string }).id
}

test.describe('认证流程', () => {
  test('错误密码给出提示', async ({ page }) => {
    await login(page, ADMIN_USERNAME, 'wrong-password-123', false)
    await expect(page.getByText('用户名或密码错误')).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('登录后刷新页面保持会话', async ({ page }) => {
    await login(page)
    await expect(page).toHaveURL(/\/agents$/)
    await expect(page.getByRole('heading', { name: '智能体管理' })).toBeVisible()

    await page.reload()
    await expect(page).toHaveURL(/\/agents$/)
    await expect(page.getByRole('heading', { name: '智能体管理' })).toBeVisible()
  })

  test('退出登录后受保护页面跳转登录', async ({ page }) => {
    await login(page)
    await page.locator('.admin-header__user').click()
    await page.getByRole('menuitem', { name: '退出登录' }).click()
    await expect(page).toHaveURL(/\/login/)

    await page.goto('/agents')
    await expect(page).toHaveURL(/\/login\?next=%2Fagents/)
  })
})

test.describe('资源与智能体', () => {
  test('技能在智能体详情内新建、编辑与删除', async ({ page, request }) => {
    const token = await adminToken(request)
    const agentName = `E2E 资源智能体 ${Date.now()}`
    const agentId = await createAgent(request, token, agentName)
    const suffix = Date.now()
    const name = `E2E 技能 ${suffix}`
    const updatedName = `${name} 已更新`

    try {
      await login(page)
      await page.goto(`/agents/${agentId}/edit`)
      await page.getByRole('tab', { name: '技能与资源' }).click()
      await page.getByRole('tab', { name: '技能', exact: true }).click()
      await expect(page.getByRole('heading', { name: '技能管理' })).toBeVisible()

      await page.getByRole('button', { name: '新建技能' }).click()
      let dialog = page.getByRole('dialog', { name: '新建技能' })
      await dialog.getByLabel('技能名称').fill(name)
      await dialog.getByLabel('描述').fill('由 Playwright 创建')
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('创建成功')).toBeVisible()

      const row = page.getByRole('row', { name: new RegExp(name) })
      await expect(row).toBeVisible()
      await row.getByRole('button', { name: /编\s*辑/ }).click()
      dialog = page.getByRole('dialog', { name: '编辑技能' })
      await dialog.getByLabel('技能名称').fill(updatedName)
      await dialog.getByRole('button', { name: '保存' }).click()
      await expect(page.getByText('保存成功')).toBeVisible()
      await expect(page.getByRole('row', { name: new RegExp(updatedName) })).toBeVisible()

      const updatedRow = page.getByRole('row', { name: new RegExp(updatedName) })
      await updatedRow.getByRole('button', { name: /删\s*除/ }).click()
      await page
        .locator('.ant-popconfirm')
        .getByRole('button', { name: /删\s*除/ })
        .click()
      await expect(page.getByText('已删除')).toBeVisible()
      await expect(page.getByRole('row', { name: new RegExp(updatedName) })).toHaveCount(0)
    } finally {
      await request.delete(`/api/v1/admin/agents/${agentId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    }
  })

  test('智能体保存后再次打开可回显', async ({ page }) => {
    const name = `E2E 智能体 ${Date.now()}`

    await login(page)
    await page.goto('/agents/new')
    await page.getByLabel('智能体名称').fill(name)
    await page.getByLabel('简介').fill('Playwright 自动化创建')
    await page.getByRole('button', { name: '保存配置' }).first().click()
    await expect(page.getByText('创建成功')).toBeVisible()
    await expect(page).toHaveURL(/\/agents$/)

    const row = page.getByRole('row', { name: new RegExp(name) })
    await row.getByRole('button', { name: /配\s*置/ }).click()
    await expect(page.getByLabel('智能体名称')).toHaveValue(name)
    await expect(page.getByLabel('简介')).toHaveValue('Playwright 自动化创建')
  })

  test('未知路径展示 404 页面', async ({ page }) => {
    await login(page)
    await page.goto('/not-exists')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
    await expect(page.getByRole('button', { name: '返回智能体管理' })).toBeVisible()
  })
})

test.describe('改密与只读权限', () => {
  test('首次登录强制改密，只读账号不可写', async ({ request, page }) => {
    const token = await adminToken(request)
    await ensureViewer(request, token)

    await login(page, VIEWER_USERNAME, VIEWER_INITIAL_PASSWORD)
    await expect(page).toHaveURL(/\/change-password/)
    await page.getByLabel('当前密码').fill(VIEWER_INITIAL_PASSWORD)
    await page.getByLabel('新密码', { exact: true }).fill(VIEWER_NEW_PASSWORD)
    await page.getByLabel('确认新密码').fill(VIEWER_NEW_PASSWORD)
    await page.getByRole('button', { name: '确认修改' }).click()
    await expect(page).toHaveURL(/\/login/)

    await login(page, VIEWER_USERNAME, VIEWER_NEW_PASSWORD)
    await expect(page).toHaveURL(/\/agents$/)
    await expect(page.getByRole('button', { name: '新建智能体' })).toHaveCount(0)

    await page.goto('/users')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
    await page.goto('/roles')
    await expect(page.getByText('页面不存在或已被移除。')).toBeVisible()
  })
})
