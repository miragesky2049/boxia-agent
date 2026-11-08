import { expect, test } from '@playwright/test'

// M4-d T-d6 真机冒烟：评测工作区全链路（数据集/用例/发起弹窗数据源/历史批报告与 diff/质量）。
// 依赖 dev 库既有数据：应用「接管冒烟主助手」与其 completed 评测批；历史批只读不重发（避免重复计费）。
// RunsPage 捕获入口已按批末裁决摘除（eval 端点组按请求上下文判平台域，任何 context 都走不通），
// 捕获链路由 T-d4 API 冒烟覆盖，UI 归属待 T-d7 连同线上采样一起裁决。

const APP_ID = '01a1b601-f0a9-73a5-8582-5f420732e565'
const USERNAME = 'smoke-eval-api'
const PASSWORD = 'BxEval-Smoke-2026'
const datasetName = `T-d6 UI集-${Date.now()}`

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.getByLabel('账号').fill(USERNAME)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: /登\s*录/ }).click()
  await page.waitForURL(/\/(apps|change-password)$/)
}

const EVAL_PATH = `/apps/${APP_ID}/eval`

test('评测页签全链路', async ({ page }) => {
  test.setTimeout(180_000)
  await login(page)

  // 从应用列表行内「评测」入口进入；列表按更新时间排序，须按目标应用行定位而非 first()
  await page.goto('/apps')
  await page.getByRole('row').filter({ hasText: '接管冒烟主助手' }).getByRole('button', { name: '评测' }).click()
  await page.waitForURL(EVAL_PATH)

  // 1) 历史冒烟数据集应可见
  await expect(page.getByText('T-d4真机集').first()).toBeVisible()

  // 2) 新建数据集 + 添加用例
  await page.getByRole('button', { name: '新建数据集' }).click()
  await page.getByPlaceholder('数据集名称').fill(datasetName)
  await page.getByRole('button', { name: /创\s*建/ }).click()
  const newRow = page.getByRole('row').filter({ hasText: datasetName })
  await expect(newRow).toBeVisible()

  await newRow.getByRole('button', { name: '用例管理' }).click()
  await page.getByPlaceholder('请输入用户问句').fill('冒烟UI问句：你好')
  await page.getByRole('button', { name: '新增用例' }).click()
  await expect(page.getByText('冒烟UI问句：你好')).toBeVisible()
  await page.getByRole('button', { name: /关\s*闭|Close/ }).first().click()

  // 3) 评估器列表含历史「恒过」
  await page.getByRole('tab', { name: '评估器' }).click()
  await expect(page.getByText('恒过').first()).toBeVisible()

  // 4) 评测运行：历史批列表 + 报告 + diff（只读，不重发批）
  await page.getByRole('tab', { name: '评测运行' }).click()
  await expect(page.getByText('已完成').first()).toBeVisible()

  await page.getByRole('button', { name: /详\s*情/ }).first().click()
  await expect(page.getByText('通过率')).toBeVisible()
  await expect(page.getByText('100%')).toBeVisible()
  // 用例管理抽屉关闭后 DOM 残留，限定当前打开的抽屉再点关闭
  await page.locator('.ant-drawer-open .ant-drawer-close').click()

  const checkboxes = page.locator('.ant-table-tbody input[type="checkbox"]')
  await checkboxes.nth(0).click()
  await checkboxes.nth(1).click()
  const diffButton = page.getByRole('button', { name: '对比选中' })
  await expect(diffButton).toBeEnabled()
  await diffButton.click()
  await expect(page.getByText('运行对比')).toBeVisible()
  // 后端 eval_result.status 为 pass，页面映射为「通过」；限定在对比弹窗内断言
  await expect(page.locator('.ant-modal-content').getByText('通过', { exact: true }).first()).toBeVisible()
  // 已关闭的 Modal 仍留 DOM，限定当前可见弹窗关闭
  await page.locator('.ant-modal-wrap:visible .ant-modal-close').click()

  // 5) 发起弹窗三数据源齐备（不提交，避免重复计费）；
  // Escape 会冒泡关闭整个 Modal 导致找不到取消按钮，收下拉改用点击弹窗标题空白处
  const closeDropdown = async () => {
    await page.locator('.ant-modal-wrap:visible .ant-modal-header').click()
  }
  await page.getByRole('button', { name: '发起评测运行' }).click()
  await page.getByRole('combobox', { name: '数据集' }).click()
  await expect(page.locator('.ant-select-item-option', { hasText: datasetName })).toBeVisible()
  await closeDropdown()
  await page.getByRole('combobox', { name: '图版本' }).click()
  await expect(page.locator('.ant-select-item-option', { hasText: /^版本 \d+$/ }).first()).toBeVisible()
  await closeDropdown()
  await page.getByRole('combobox', { name: '评估器' }).click()
  await expect(page.locator('.ant-select-item-option', { hasText: '恒过' }).first()).toBeVisible()
  await closeDropdown()
  // 应用未配 zh_CN locale，Modal 默认取消按钮文案为英文 Cancel
  await page.getByRole('button', { name: /取\s*消|Cancel/ }).click()

  // 6) 质量页签骨架指标
  await page.getByRole('tab', { name: '质量' }).click()
  await expect(page.getByText('评测批次数')).toBeVisible()

})
