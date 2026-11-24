import { chromium } from '@playwright/test'
import fs from 'node:fs'

const OUT = 'D:/OtherCode/PythonProject/boxia-agent/docs/assets/screenshots'
fs.mkdirSync(OUT, { recursive: true })

const shot = async (page, name) => {
  await page.screenshot({ path: `${OUT}/${name}.png` })
  console.log('saved', name)
}

const fillField = async (page, label, placeholder, value) => {
  const byLabel = page.getByLabel(label)
  if (await byLabel.count()) await byLabel.first().fill(value)
  else await page.getByPlaceholder(placeholder).fill(value)
}

const login = async (page, base, user, pass, shotName, urlPattern) => {
  await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
  await fillField(page, '账号', /请输入(管理员)?账号/, user)
  await fillField(page, '密码', /请输入(登录)?密码/, pass)
  const tenantField = page.getByLabel(/租户编码/)
  if (await tenantField.count()) await tenantField.first().fill('wfco')
  await shot(page, shotName)
  await page.getByRole('button', { name: /登/ }).first().click()
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15000 })
  await page.waitForTimeout(1800)
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })

// ---- 管理端：产品级平台 ----
const admin = await ctx.newPage()
await login(admin, 'http://localhost:5173', 'shot-admin', 'Screenshot-pass-123', 'admin-login')
await admin.waitForLoadState('networkidle')
await shot(admin, 'admin-apps')

// 画布编排：由环境变量传入 dag 应用 id，直接进编辑页
const dagAppId = process.env.DAG_APP_ID
if (dagAppId) {
  await admin.goto(`http://localhost:5173/apps/${dagAppId}/edit`, { waitUntil: 'networkidle' })
  await admin.waitForTimeout(3500)
  await shot(admin, 'admin-canvas')
} else {
  console.log('WARN: DAG_APP_ID not provided, skip canvas shot')
}

for (const [path, name] of [
  ['/marketplace', 'admin-marketplace'],
  ['/resources', 'admin-resources'],
  ['/tenants', 'admin-tenants'],
  ['/audit', 'admin-audit'],
]) {
  await admin.goto(`http://localhost:5173${path}`, { waitUntil: 'networkidle' })
  await admin.waitForTimeout(800)
  await shot(admin, name)
}

// ---- 管理端：租户视角（wfco 子域） ----
const tenantAdmin = await ctx.newPage()
await login(
  tenantAdmin,
  'http://wfco.localhost:5173',
  'wfco-admin',
  'Tenant-password-123',
  'tenant-login',
)
await tenantAdmin.waitForLoadState('networkidle')
await shot(tenantAdmin, 'tenant-apps')
await tenantAdmin.goto('http://wfco.localhost:5173/users', { waitUntil: 'networkidle' })
await tenantAdmin.waitForTimeout(800)
await shot(tenantAdmin, 'tenant-users')

// ---- 用户端门户：最终用户 ----
const user = await ctx.newPage()
await login(user, 'http://wfco.localhost:5174', 'wf-owner', 'User-password-123', 'user-login')
await user.waitForLoadState('networkidle')
await shot(user, 'user-apps')
const agentHref = await user
  .locator('a[href*="/agents/"]')
  .first()
  .getAttribute('href')
  .catch(() => null)
if (agentHref) {
  await user.goto(`http://wfco.localhost:5174${agentHref}`, { waitUntil: 'networkidle' })
  await user.waitForTimeout(1500)
  await shot(user, 'user-chat')
} else {
  console.log('WARN: no agent link found on user portal')
}

await browser.close()
console.log('done')
