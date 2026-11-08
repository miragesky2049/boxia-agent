import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from '../auth/tokenStore'
import {
  captureCaseFromRun,
  createDataset,
  diffEvalRuns,
  getQualitySummary,
  listDatasets,
  startEvalRun,
} from './eval'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('eval api', () => {
  it('listDatasets 带 application_id 过滤参数', async () => {
    setAccessToken('t')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await listDatasets('app-1')
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      '/api/v1/admin/eval/datasets?application_id=app-1',
    )
  })

  it('createDataset 提交 application_id/name/description', async () => {
    setAccessToken('t')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'd1' }, 201))
    vi.stubGlobal('fetch', fetchMock)
    await createDataset({ application_id: 'app-1', name: '集', description: 'x' })
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/v1/admin/eval/datasets')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      application_id: 'app-1',
      name: '集',
      description: 'x',
    })
  })

  it('startEvalRun 提交发起体并返回 eval_run_id', async () => {
    setAccessToken('t')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ eval_run_id: 'r1' }, 201))
    vi.stubGlobal('fetch', fetchMock)
    const runId = await startEvalRun({
      dataset_id: 'd1',
      graph_version: 3,
      evaluator_ids: ['e1', 'e2'],
      concurrency: 4,
    })
    expect(runId).toBe('r1')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/v1/admin/eval/eval-runs')
    expect(JSON.parse(String(init.body))).toEqual({
      dataset_id: 'd1',
      graph_version: 3,
      evaluator_ids: ['e1', 'e2'],
      concurrency: 4,
    })
  })

  it('diffEvalRuns 与 captureCaseFromRun 路径口径', async () => {
    setAccessToken('t')
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ items: [] }))
      .mockResolvedValueOnce(jsonResponse({ id: 'c1' }, 201))
    vi.stubGlobal('fetch', fetchMock)
    await diffEvalRuns('r1', 'r2')
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      '/api/v1/admin/eval/eval-runs/diff?run_a=r1&run_b=r2',
    )
    await captureCaseFromRun('d1', 'run-9')
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit]
    expect(url).toContain('/api/v1/admin/eval/datasets/d1/cases/from-run')
    expect(JSON.parse(String(init.body))).toEqual({ run_id: 'run-9' })
  })

  it('getQualitySummary 缺省 7 天窗口、显式传 days 透查询参数', async () => {
    setAccessToken('t')
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)
    await getQualitySummary('app-1')
    expect(fetchMock.mock.calls[0]?.[0]).toContain(
      '/api/v1/admin/apps/app-1/quality/summary?days=7',
    )
    await getQualitySummary('app-1', 30)
    expect(fetchMock.mock.calls[1]?.[0]).toContain(
      '/api/v1/admin/apps/app-1/quality/summary?days=30',
    )
  })
})
