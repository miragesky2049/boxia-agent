import { request } from './client'

export interface EvalDataset {
  id: string
  application_id: string
  name: string
  description: string
  created_at?: string | null
  updated_at?: string | null
}

export interface EvalCase {
  id: string
  dataset_id: string
  input: Record<string, unknown>
  expected: string | null
  expected_tool_calls: Record<string, unknown> | null
  position: number
}

export interface EvalEvaluator {
  id: string
  name: string
  type: 'rule' | 'llm_judge'
  config: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
}

export interface EvalRun {
  id: string
  application_id?: string | null
  graph_version: number
  dataset_id: string
  evaluator_ids: string[]
  status: string
  progress: Record<string, number> | null
  usage: Record<string, number> | null
  error_message: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface EvalResult {
  id: string
  run_id: string | null
  case_id: string | null
  status: string
  score: number | null
  reason: string
  judge_usage: Record<string, number> | null
  source: string
  created_at?: string | null
}

export interface EvalRunDetail {
  run: EvalRun
  results: EvalResult[]
  summary: { total: number; passed: number; failed: number; errored: number; pass_rate: number }
}

export interface EvalDiffItem {
  case_id: string
  position: number
  status_a: string | null
  score_a: number | null
  reason_a: string | null
  status_b: string | null
  score_b: number | null
  reason_b: string | null
}

// T-d9 看板：逐日采样趋势点（UTC 日，缺样本日补零行）
export interface QualityTrendPoint {
  date: string
  count: number
  avg_score: number | null
}

// T-d9 低分清单行：run_id 即飞轮入口（from-run 转评测集）的入参
export interface QualityLowItem {
  run_id: string
  question: string
  status: string
  score: number | null
  reason: string
  created_at: string | null
}

export interface QualitySummary {
  window_days: number
  eval_batches: { count: number; latest_pass_rate: number | null }
  runtime_samples: { count: number; avg_score: number | null; low_score_count: number }
  trend: QualityTrendPoint[]
  low_score_items: QualityLowItem[]
}

export async function listDatasets(applicationId: string): Promise<EvalDataset[]> {
  const res = await request<{ items: EvalDataset[] }>(
    `/admin/eval/datasets?application_id=${encodeURIComponent(applicationId)}`,
  )
  return res.items
}

export async function createDataset(payload: {
  application_id: string
  name: string
  description?: string
}): Promise<EvalDataset> {
  return request<EvalDataset>('/admin/eval/datasets', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteDataset(datasetId: string): Promise<void> {
  await request<void>(`/admin/eval/datasets/${datasetId}`, { method: 'DELETE' })
}

export async function listCases(datasetId: string): Promise<EvalCase[]> {
  const res = await request<{ items: EvalCase[] }>(`/admin/eval/datasets/${datasetId}/cases`)
  return res.items
}

export async function addCase(
  datasetId: string,
  payload: {
    input: Record<string, unknown>
    expected?: string | null
    expected_tool_calls?: Record<string, unknown> | null
  },
): Promise<EvalCase> {
  return request<EvalCase>(`/admin/eval/datasets/${datasetId}/cases`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function deleteCase(caseId: string): Promise<void> {
  await request<void>(`/admin/eval/cases/${caseId}`, { method: 'DELETE' })
}

export async function captureCaseFromRun(datasetId: string, runId: string): Promise<EvalCase> {
  return request<EvalCase>(`/admin/eval/datasets/${datasetId}/cases/from-run`, {
    method: 'POST',
    body: JSON.stringify({ run_id: runId }),
  })
}

export async function listEvaluators(): Promise<EvalEvaluator[]> {
  const res = await request<{ items: EvalEvaluator[] }>('/admin/eval/evaluators')
  return res.items
}

export async function createEvaluator(payload: {
  name: string
  type: 'rule' | 'llm_judge'
  config: Record<string, unknown>
}): Promise<EvalEvaluator> {
  return request<EvalEvaluator>('/admin/eval/evaluators', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateEvaluator(
  evaluatorId: string,
  payload: { name: string; type: 'rule' | 'llm_judge'; config: Record<string, unknown> },
): Promise<EvalEvaluator> {
  return request<EvalEvaluator>(`/admin/eval/evaluators/${evaluatorId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteEvaluator(evaluatorId: string): Promise<void> {
  await request<void>(`/admin/eval/evaluators/${evaluatorId}`, { method: 'DELETE' })
}

export async function startEvalRun(payload: {
  dataset_id: string
  graph_version: number
  evaluator_ids: string[]
  concurrency: number
}): Promise<string> {
  const res = await request<{ eval_run_id: string }>('/admin/eval/eval-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return res.eval_run_id
}

export async function listEvalRuns(applicationId: string): Promise<EvalRun[]> {
  const res = await request<{ items: EvalRun[] }>(
    `/admin/eval/eval-runs?application_id=${encodeURIComponent(applicationId)}`,
  )
  return res.items
}

export async function getEvalRunDetail(evalRunId: string): Promise<EvalRunDetail> {
  return request<EvalRunDetail>(`/admin/eval/eval-runs/${evalRunId}`)
}

export async function diffEvalRuns(runA: string, runB: string): Promise<EvalDiffItem[]> {
  const res = await request<{ items: EvalDiffItem[] }>(
    `/admin/eval/eval-runs/diff?run_a=${runA}&run_b=${runB}`,
  )
  return res.items
}

export async function getQualitySummary(applicationId: string, days = 7): Promise<QualitySummary> {
  return request<QualitySummary>(`/admin/apps/${applicationId}/quality/summary?days=${days}`)
}
