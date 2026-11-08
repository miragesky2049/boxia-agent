import { App as AntdApp } from 'antd'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from '../../../auth/tokenStore'
import EvalPanel from './EvalPanel'

// T-d6：admin 评测页签（数据集/评估器/评测运行/质量）。组件不依赖登录上下文，
// 只按 applicationId 拉评测数据，fetch 按 pathname 分发。

const datasetA = {
  id: 'd1',
  application_id: 'app-1',
  name: '问答基线集',
  description: '冷启动捕获',
}
const caseOne = {
  id: 'c1',
  dataset_id: 'd1',
  input: { message: '退货政策是什么' },
  expected: '7天无理由',
  expected_tool_calls: null,
  position: 0,
}
const evaluatorRule = {
  id: 'e1',
  name: '关键词断言',
  type: 'rule',
  config: { contains: '7天' },
}
const runRunning = {
  id: 'r1',
  application_id: 'app-1',
  graph_version: 2,
  dataset_id: 'd1',
  evaluator_ids: ['e1'],
  status: 'running',
  progress: { total: 5, done: 2 },
  usage: null,
  error_message: null,
}
const runCompleted = {
  ...runRunning,
  status: 'completed',
  progress: { total: 5, done: 5 },
}
const runOld = { ...runCompleted, id: 'r0', graph_version: 1 }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface Route {
  match: RegExp
  method?: string
  body?: unknown
  status?: number
}

interface FetchCall {
  method: string
  pathname: string
  search?: string
  body?: unknown
}

let calls: FetchCall[] = []
let handlers: Route[] = []
let fallback: (pathname: string) => unknown = () => ({ items: [] })

function setupFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    const parsed = new URL(url, 'http://localhost')
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, pathname: parsed.pathname, search: parsed.search, body })
    const route = handlers.find(
      (h) => h.match.test(parsed.pathname) && (h.method ?? 'GET') === method,
    )
    if (route) return jsonResponse(route.body ?? {}, route.status ?? 200)
    return jsonResponse(fallback(parsed.pathname))
  })
  vi.stubGlobal('fetch', fetchMock)
}

function route(pathnamePattern: string, body: unknown, method = 'GET'): void {
  handlers.push({ match: new RegExp(pathnamePattern), method, body })
}

function findCall(method: string, pathnamePart: string): FetchCall | undefined {
  return calls.find((c) => c.method === method && c.pathname.includes(pathnamePart))
}

function renderPanel() {
  return render(
    <AntdApp>
      <EvalPanel applicationId="app-1" />
    </AntdApp>,
  )
}

beforeEach(() => {
  setAccessToken('t')
  calls = []
  handlers = []
  fallback = () => ({ items: [] })
  setupFetch()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('EvalPanel 数据集', () => {
  it('初始渲染四个页签并按应用拉数据集', async () => {
    route('/admin/eval/datasets$', { items: [datasetA] })
    renderPanel()
    for (const label of ['数据集', '评估器', '评测运行', '质量']) {
      expect(screen.getByRole('tab', { name: label })).toBeTruthy()
    }
    await waitFor(() =>
      expect(findCall('GET', '/admin/eval/datasets')?.search).toContain('application_id=app-1'),
    )
  })

  it('新建数据集提交 application_id/name/description 并刷新列表', async () => {
    route('/admin/eval/datasets$', { items: [] })
    route('/admin/eval/datasets$', { ...datasetA, id: 'd9', name: '新版本集' }, 'POST')
    renderPanel()
    await waitFor(() => expect(findCall('GET', '/admin/eval/datasets')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '新建数据集' }))
    fireEvent.change(screen.getByPlaceholderText('数据集名称'), { target: { value: '新版本集' } })
    fireEvent.change(screen.getByPlaceholderText('描述（选填）'), { target: { value: 'v2 对比' } })
    fireEvent.click(screen.getByRole('button', { name: '创 建' }))
    await waitFor(() => expect(findCall('POST', '/admin/eval/datasets')).toBeTruthy())
    expect(findCall('POST', '/admin/eval/datasets')?.body).toEqual({
      application_id: 'app-1',
      name: '新版本集',
      description: 'v2 对比',
    })
  })

  it('用例管理打开抽屉拉取用例并可删除', async () => {
    route('/admin/eval/datasets$', { items: [datasetA] })
    route('/admin/eval/datasets/d1/cases$', { items: [caseOne] })
    route('/admin/eval/cases/c1', {}, 'DELETE')
    renderPanel()
    await waitFor(() => expect(screen.getByText('问答基线集')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '用例管理' }))
    await waitFor(() => expect(screen.getByText('退货政策是什么')).toBeTruthy())
    // 数据集行内也有「删除」按钮，抽屉后挂载取最后一个
    const deleteButtons = screen.getAllByRole('button', { name: /^删\s?除$/ })
    fireEvent.click(deleteButtons[deleteButtons.length - 1]!)
    await waitFor(() => expect(findCall('DELETE', '/admin/eval/cases/c1')).toBeTruthy())
  })
})

describe('EvalPanel 评估器', () => {
  it('切到评估器页签拉列表；config 非法 JSON 时不落请求', async () => {
    route('/admin/eval/evaluators$', { items: [evaluatorRule] })
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '评估器' }))
    await waitFor(() => expect(screen.getByText('关键词断言')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '新建评估器' }))
    // openCreate 用 requestAnimationFrame 延后 setFieldsValue，先等一帧再输入，避免默认值覆盖已填内容
    await act(async () => {
      await new Promise((resolve) => requestAnimationFrame(resolve))
    })
    fireEvent.change(screen.getByPlaceholderText('评估器名称'), { target: { value: '格式校验' } })
    fireEvent.change(screen.getByPlaceholderText('配置 JSON'), { target: { value: '{oops' } })
    fireEvent.click(screen.getByRole('button', { name: '保 存' }))
    await waitFor(() => expect(screen.getByText('配置必须是合法 JSON')).toBeTruthy())
    expect(findCall('POST', '/admin/eval/evaluators')).toBeFalsy()
  })

  it('新建评估器提交 name/type/config', async () => {
    route('/admin/eval/evaluators$', { items: [] })
    route(
      '/admin/eval/evaluators$',
      { id: 'e9', name: '语义判定', type: 'llm_judge', config: {} },
      'POST',
    )
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '评估器' }))
    await waitFor(() => expect(findCall('GET', '/admin/eval/evaluators')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '新建评估器' }))
    fireEvent.change(screen.getByPlaceholderText('评估器名称'), { target: { value: '语义判定' } })
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '类型' }))
    fireEvent.click(
      await screen.findByText('LLM 判定', { selector: '.ant-select-item-option-content' }),
    )
    fireEvent.change(screen.getByPlaceholderText('配置 JSON'), {
      target: { value: '{"criteria":"回答与期望语义一致"}' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保 存' }))
    await waitFor(() => expect(findCall('POST', '/admin/eval/evaluators')).toBeTruthy())
    expect(findCall('POST', '/admin/eval/evaluators')?.body).toEqual({
      name: '语义判定',
      type: 'llm_judge',
      config: { criteria: '回答与期望语义一致' },
    })
  })
})

describe('EvalPanel 评测运行', () => {
  it('发起弹窗汇聚数据集/版本/评估器数据源并提交运行体', async () => {
    route('/admin/eval/datasets$', { items: [datasetA] })
    route('/admin/eval/evaluators$', { items: [evaluatorRule] })
    route('/admin/apps/app-1/graph-versions$', [
      {
        id: 'v2',
        version: 2,
        runtime_mode: 'agent_loop',
        changelog: null,
        created_by: null,
        created_at: '2026-01-02T00:00:00Z',
      },
      {
        id: 'v1',
        version: 1,
        runtime_mode: 'agent_loop',
        changelog: null,
        created_by: null,
        created_at: '2026-01-01T00:00:00Z',
      },
    ])
    route('/admin/eval/eval-runs$', { items: [] })
    route('/admin/eval/eval-runs$', { eval_run_id: 'r9' }, 'POST')
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '评测运行' }))
    await waitFor(() => expect(findCall('GET', '/admin/eval/eval-runs')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: '发起评测运行' }))
    // rc-select 的 role=option 节点是隐藏 a11y 列表，必须点可见 option 内容才触发选择
    const visibleOption = (text: string) =>
      screen.findByText(text, { selector: '.ant-select-item-option-content' })
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '数据集' }))
    fireEvent.click(await visibleOption('问答基线集'))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '图版本' }))
    fireEvent.click(await visibleOption('版本 2'))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '评估器' }))
    fireEvent.click(await visibleOption('关键词断言'))
    fireEvent.click(screen.getByRole('button', { name: '发 起' }))
    await waitFor(() => expect(findCall('POST', '/admin/eval/eval-runs')).toBeTruthy())
    expect(findCall('POST', '/admin/eval/eval-runs')?.body).toEqual({
      dataset_id: 'd1',
      graph_version: 2,
      evaluator_ids: ['e1'],
      concurrency: 2,
    })
  })

  it('running 批存在时每 5 秒轮询，终态后停止', async () => {
    vi.useFakeTimers()
    let runs: unknown[] = [runRunning]
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const pathname = new URL(String(input), 'http://localhost').pathname
      calls.push({ method: (init?.method ?? 'GET').toUpperCase(), pathname })
      if (pathname.includes('/admin/eval/eval-runs')) return jsonResponse({ items: runs })
      return jsonResponse({ items: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '评测运行' }))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(screen.getByText('运行中')).toBeTruthy()

    runs = [runCompleted]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })
    expect(screen.getByText('已完成')).toBeTruthy()
    const before = calls.filter((c) => c.pathname.includes('/eval-runs')).length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000)
    })
    expect(calls.filter((c) => c.pathname.includes('/eval-runs')).length).toBe(before)
  })

  it('运行详情展示通过率与逐用例结果', async () => {
    route('/admin/eval/eval-runs$', { items: [runCompleted] })
    route('/admin/eval/eval-runs/r1$', {
      run: runCompleted,
      results: [
        {
          id: 'x1',
          run_id: 'r1',
          case_id: 'c1',
          status: 'pass',
          score: 1,
          reason: '命中关键词',
          judge_usage: null,
          source: 'evaluator',
        },
      ],
      summary: { total: 5, passed: 4, failed: 1, errored: 0, pass_rate: 0.8 },
    })
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '评测运行' }))
    await waitFor(() => expect(screen.getByText('已完成')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: /^详\s?情$/ }))
    await waitFor(() => expect(screen.getByText('80%')).toBeTruthy())
    expect(await screen.findByText('命中关键词')).toBeTruthy()
  })

  it('勾选两条运行后对比，按勾选顺序传 run_a/run_b', async () => {
    route('/admin/eval/eval-runs$', { items: [runOld, runCompleted] })
    route('/admin/eval/eval-runs/diff$', {
      items: [
        {
          case_id: 'c1',
          position: 0,
          status_a: 'pass',
          score_a: 1,
          reason_a: 'ok',
          status_b: 'fail',
          score_b: 0,
          reason_b: '缺少关键词',
        },
      ],
    })
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '评测运行' }))
    await waitFor(() => expect(screen.getAllByText('已完成')).toHaveLength(2))

    const diffButton = screen.getByRole('button', { name: '对比选中' })
    expect((diffButton as HTMLButtonElement).disabled).toBe(true)
    // hideSelectAll 后行选框即第 0/1 个 checkbox
    const checkboxes = screen.getAllByRole('checkbox')
    fireEvent.click(checkboxes[0]!)
    fireEvent.click(checkboxes[1]!)
    fireEvent.click(screen.getByRole('button', { name: '对比选中' }))
    await waitFor(() =>
      expect(findCall('GET', '/admin/eval/eval-runs/diff')?.search).toContain('run_a=r0&run_b=r1'),
    )
    expect(await screen.findByText('缺少关键词')).toBeTruthy()
    // 后端 status 原值 pass/fail 应映射为中文展示
    expect(screen.getByText('未通过')).toBeTruthy()
  })
})

const qualitySummaryBoard = {
  window_days: 7,
  eval_batches: { count: 3, latest_pass_rate: 0.8 },
  runtime_samples: { count: 42, avg_score: 6.5, low_score_count: 5 },
  trend: [
    { date: '2026-11-01', count: 0, avg_score: null },
    { date: '2026-11-02', count: 0, avg_score: null },
    { date: '2026-11-03', count: 0, avg_score: null },
    { date: '2026-11-04', count: 0, avg_score: null },
    { date: '2026-11-05', count: 0, avg_score: null },
    { date: '2026-11-06', count: 0, avg_score: null },
    { date: '2026-11-07', count: 42, avg_score: 6.5 },
  ],
  low_score_items: [
    {
      run_id: 'run-low',
      question: '极光是什么',
      status: 'fail',
      score: 3,
      reason: '答非所问',
      created_at: '2026-11-07T10:00:00Z',
    },
  ],
}

describe('EvalPanel 质量', () => {
  it('质量页签拉 summary 并渲染关键指标', async () => {
    route('/admin/apps/app-1/quality/summary', qualitySummaryBoard)
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '质量' }))
    await waitFor(() => expect(findCall('GET', '/quality/summary')).toBeTruthy())
    // 概览数字与趋势/低分表内数字可能同值，按 descriptions 内容单元格定位
    const metrics = '.ant-descriptions-item-content'
    expect(await screen.findByText('3', { selector: metrics })).toBeTruthy()
    expect(screen.getByText('42', { selector: metrics })).toBeTruthy()
    expect(screen.getByText('5', { selector: metrics })).toBeTruthy()
  })

  it('渲染逐日趋势与低分清单，低分行一键加入评测集（F18.6 飞轮）', async () => {
    route('/admin/apps/app-1/quality/summary', qualitySummaryBoard)
    route('/admin/eval/datasets$', { items: [datasetA] })
    route('/admin/eval/datasets/d1/cases/from-run', { ...caseOne, id: 'c9' }, 'POST')
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '质量' }))
    await waitFor(() => expect(screen.getByText('极光是什么')).toBeTruthy())
    // 趋势表透出窗口内有数据的一天（零样本日也成行，均分显示 —）
    expect(screen.getByText('2026-11-07')).toBeTruthy()
    expect(screen.getByText('2026-11-01')).toBeTruthy()
    expect(screen.getByText('答非所问')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '加入评测集' }))
    await waitFor(() => expect(findCall('GET', '/admin/eval/datasets')).toBeTruthy())
    fireEvent.click(screen.getByRole('radio', { name: '问答基线集' }))
    fireEvent.click(screen.getByRole('button', { name: '导 入' }))
    await waitFor(() => expect(findCall('POST', '/cases/from-run')).toBeTruthy())
    expect(findCall('POST', '/cases/from-run')?.body).toEqual({ run_id: 'run-low' })
  })

  it('切换窗口天数按 days 参数重新请求', async () => {
    route('/admin/apps/app-1/quality/summary', qualitySummaryBoard)
    renderPanel()
    fireEvent.click(screen.getByRole('tab', { name: '质量' }))
    await waitFor(() => expect(findCall('GET', '/quality/summary')?.search).toContain('days=7'))
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '统计窗口' }))
    fireEvent.click(
      await screen.findByText('近 14 天', { selector: '.ant-select-item-option-content' }),
    )
    await waitFor(() =>
      expect(calls.filter((c) => c.pathname.includes('/quality/summary'))).toHaveLength(2),
    )
    const second = calls.filter((c) => c.pathname.includes('/quality/summary'))[1]
    expect(second?.search).toContain('days=14')
  })
})
