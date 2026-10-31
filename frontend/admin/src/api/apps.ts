import { request } from './client'
import { getAccessToken } from '../auth/tokenStore'
import { getTenantCode } from '../tenant/scope'

// ========== 应用 graph ==========
export interface GraphNode {
  id: string
  type: string
  position?: { x: number; y: number }
  config?: Record<string, unknown>
}

export interface GraphEdge {
  from: string
  to: string
  type?: 'normal' | 'feedback'
  when?: string
}

export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface Application {
  id: string
  owner_type: 'platform' | 'tenant'
  owner_id: string | null
  name: string
  avatar_url: string | null
  description: string
  is_enabled: boolean
  is_listed_in_market: boolean
  visibility_mode: 'all' | 'custom'
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface ApplicationGraph extends Application {
  graph: Graph
  runtime_mode: 'dag' | 'agent_loop'
}

export interface MarketplaceItem {
  id: string
  name: string
  avatar_url: string | null
  description: string
}

export interface MyApp {
  id: string
  tenant_id: string
  application_id: string
  status: 'active' | 'suspended' | 'disabled' | 'revoked'
  source: 'marketplace' | 'custom'
  name: string
  description: string
  avatar_url: string | null
  created_at: string
}

// ========== 模型目录 ==========
export interface ModelItem {
  model_id: string
  display_name: string
  capabilities: Record<string, unknown>
  provider_name: string
}

export interface ModelCatalogItem extends ModelItem {
  id: string
  provider_id: string
  is_enabled: boolean
  base_url: string
}

export interface Provider {
  id: string
  name: string
  base_url: string
  owner_type: 'platform' | 'tenant'
  owner_id: string | null
  is_enabled: boolean
  created_at: string
}

// ========== 市场接口（租户端） ==========
export async function listMarketplace(): Promise<MarketplaceItem[]> {
  return request<MarketplaceItem[]>('/admin/marketplace/applications')
}

export async function subscribeApplication(applicationId: string): Promise<{
  instance_id: string
  application_id: string
}> {
  return request<{ instance_id: string; application_id: string }>(
    '/admin/marketplace/subscribe',
    {
      method: 'POST',
      body: JSON.stringify({ application_id: applicationId }),
    },
  )
}

export async function listMyApps(): Promise<MyApp[]> {
  return request<MyApp[]>('/admin/marketplace/my-apps')
}

// ========== 运行历史 ==========
export interface RunItem {
  id: string
  application_id: string
  langgraph_thread_id: string
  status: 'running' | 'success' | 'error' | 'interrupted'
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  error: string | null
  started_at: string
  finished_at: string | null
}

export interface NodeExecution {
  id: string
  node_id: string
  node_type: string
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  error: string | null
  started_at: string
  finished_at: string | null
  duration_ms: number | null
  token_usage: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
  } | null
}

export interface RunDetail {
  run: RunItem & {
    tenant_id: string
  }
  node_executions: NodeExecution[]
}

export async function listApplicationRuns(
  applicationId: string,
  limit = 50,
): Promise<RunItem[]> {
  return request<RunItem[]>(
    `/admin/marketplace/applications/${applicationId}/runs?limit=${limit}`,
  )
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/admin/marketplace/runs/${runId}`)
}

export interface CheckpointItem {
  checkpoint_id: string
  next_nodes: string[]
  input: Record<string, unknown> | null
  output: Record<string, unknown> | null
  node_count: number
  created_at: string | null
}

export async function listRunCheckpoints(runId: string): Promise<CheckpointItem[]> {
  const data = await request<{ checkpoints: CheckpointItem[] }>(
    `/admin/marketplace/runs/${runId}/checkpoints`,
  )
  return data.checkpoints ?? []
}

export async function forkRun(
  runId: string,
  payload: { checkpoint_id: string; new_input?: Record<string, unknown> },
): Promise<{
  status: 'success' | 'waiting_approval'
  new_run_id: string
  new_thread_id: string
  output?: Record<string, unknown>
  approval?: Record<string, unknown>
}> {
  return request<{
    status: 'success' | 'waiting_approval'
    new_run_id: string
    new_thread_id: string
    output?: Record<string, unknown>
    approval?: Record<string, unknown>
  }>(`/admin/marketplace/runs/${runId}/fork`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function resumeRun(
  applicationId: string,
  threadId: string,
  payload: { approved: boolean; comment: string },
): Promise<{
  status: 'success' | 'waiting_approval'
  output?: Record<string, unknown>
  thread_id: string
  run_id: string
  approval?: Record<string, unknown>
}> {
  return request<{
    status: 'success' | 'waiting_approval'
    output?: Record<string, unknown>
    thread_id: string
    run_id: string
    approval?: Record<string, unknown>
  }>(`/admin/marketplace/applications/${applicationId}/runs/${threadId}/resume`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export type RunResult = {
  status: 'success' | 'waiting_approval'
  output?: Record<string, unknown>
  thread_id: string
  run_id: string
  approval?: Record<string, unknown>
}

export async function runApplication(
  applicationId: string,
  inputs: Record<string, unknown>,
): Promise<RunResult> {
  return request<RunResult>(`/admin/marketplace/applications/${applicationId}/run`, {
    method: 'POST',
    body: JSON.stringify({ inputs }),
  })
}

// ========== 应用输入变量 ==========
export interface ApplicationInput {
  name: string
  type: 'string' | 'number' | 'boolean' | 'json'
  required?: boolean
  default?: string | number | boolean | null
}

export async function getApplicationInputs(
  applicationId: string,
): Promise<ApplicationInput[]> {
  const data = await request<{ inputs: ApplicationInput[] }>(
    `/admin/marketplace/applications/${applicationId}/inputs`,
  )
  return data.inputs ?? []
}

// ========== 统一资源（tool / prompt / skill / knowledge） ==========
export type ResourceType = 'tool' | 'prompt' | 'skill' | 'knowledge'

export interface Resource {
  id: string
  type: ResourceType
  owner_type: 'platform' | 'tenant'
  owner_id: string | null
  name: string
  config: Record<string, unknown>
  version: number
  is_enabled: boolean
  is_deprecated: boolean
  created_at: string
}

export interface ResourceGrant {
  id: string
  resource_id: string
  tenant_id: string
  granted_at: string
}

export async function listResources(params: {
  type?: ResourceType
  owner_type?: 'platform' | 'tenant'
} = {}): Promise<Resource[]> {
  const query = new URLSearchParams()
  if (params.type) query.set('type', params.type)
  if (params.owner_type) query.set('owner_type', params.owner_type)
  const qs = query.toString()
  return request<Resource[]>(`/admin/resources${qs ? `?${qs}` : ''}`)
}

export async function getResource(resourceId: string): Promise<Resource> {
  return request<Resource>(`/admin/resources/${resourceId}`)
}

export async function createResource(payload: {
  type: ResourceType
  name: string
  config: Record<string, unknown>
}): Promise<{ resource_id: string }> {
  return request<{ resource_id: string }>('/admin/resources', {
    method: 'POST',
    body: JSON.stringify({ ...payload, owner_type: 'platform' }),
  })
}

export async function updateResource(
  resourceId: string,
  payload: {
    name?: string
    config?: Record<string, unknown>
    is_enabled?: boolean
    is_deprecated?: boolean
  },
): Promise<void> {
  await request<void>(`/admin/resources/${resourceId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteResource(resourceId: string): Promise<void> {
  await request<void>(`/admin/resources/${resourceId}`, { method: 'DELETE' })
}

export async function listResourceGrants(resourceId: string): Promise<ResourceGrant[]> {
  return request<ResourceGrant[]>(`/admin/resources/${resourceId}/grants`)
}

export async function grantResource(
  resourceId: string,
  tenantId: string,
): Promise<void> {
  await request<void>(`/admin/resources/${resourceId}/grants`, {
    method: 'POST',
    body: JSON.stringify({ tenant_id: tenantId }),
  })
}

export async function revokeResourceGrant(
  resourceId: string,
  tenantId: string,
): Promise<void> {
  await request<void>(`/admin/resources/${resourceId}/grants/${tenantId}`, {
    method: 'DELETE',
  })
}

// ========== 平台应用管理 ==========
export async function listApps(params: {
  owner_type?: string
  marketplace_only?: boolean
} = {}): Promise<Application[]> {
  const query = new URLSearchParams()
  if (params.owner_type) query.set('owner_type', params.owner_type)
  if (params.marketplace_only) query.set('marketplace_only', 'true')
  const qs = query.toString()
  return request<Application[]>(`/admin/apps${qs ? `?${qs}` : ''}`)
}

export async function createApp(payload: {
  name: string
  description?: string
}): Promise<{ application_id: string }> {
  return request<{ application_id: string }>('/admin/apps', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getApp(applicationId: string): Promise<Application> {
  return request<Application>(`/admin/apps/${applicationId}`)
}

export async function updateApp(
  applicationId: string,
  payload: { name?: string; description?: string; avatar_url?: string | null },
): Promise<void> {
  await request<void>(`/admin/apps/${applicationId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function getAppGraph(applicationId: string): Promise<{
  graph: Graph
  runtime_mode: 'dag' | 'agent_loop'
  graph_schema_version: number
}> {
  return request<{ graph: Graph; runtime_mode: 'dag' | 'agent_loop'; graph_schema_version: number }>(
    `/admin/apps/${applicationId}/graph`,
  )
}

export async function saveAppGraph(
  applicationId: string,
  graph: Graph,
): Promise<{
  runtime_mode: 'dag' | 'agent_loop'
  versioned_fields: Array<{
    path: string
    old: unknown
    new: unknown
    version: number
  }>
}> {
  return request<{
    runtime_mode: 'dag' | 'agent_loop'
    versioned_fields: Array<{ path: string; old: unknown; new: unknown; version: number }>
  }>(`/admin/apps/${applicationId}/graph`, {
    method: 'PUT',
    body: JSON.stringify({ graph }),
  })
}

// ========== 版本历史（B9） ==========
export interface GraphVersionItem {
  id: string
  version: number
  runtime_mode: 'dag' | 'agent_loop'
  changelog: string | null
  created_by: string | null
  created_at: string
}

export async function listGraphVersions(applicationId: string): Promise<GraphVersionItem[]> {
  return request<GraphVersionItem[]>(`/admin/apps/${applicationId}/graph-versions`)
}

export async function rollbackGraph(
  applicationId: string,
  version: number,
): Promise<{ ok: boolean; new_version?: number }> {
  return request<{ ok: boolean; new_version?: number }>(`/admin/apps/${applicationId}/graph-rollback`, {
    method: 'POST',
    body: JSON.stringify({ version }),
  })
}

// ========== 字段级版本 ==========
export interface FieldVersion {
  field_path: string
  version: number
  value: unknown
  changelog: string
  published_at: string | null
  created_at: string
}

export interface EffectiveField {
  version: number
  value: unknown
  pinned: boolean
}

export interface FieldPin {
  field_path: string
  pinned_version: number
  created_at: string
}

export async function listFieldVersions(
  applicationId: string,
  fieldPath?: string,
): Promise<FieldVersion[]> {
  const qs = fieldPath ? `?field_path=${encodeURIComponent(fieldPath)}` : ''
  return request<FieldVersion[]>(`/admin/apps/${applicationId}/field-versions${qs}`)
}

export async function getEffectiveConfig(
  applicationId: string,
  tenantId?: string,
): Promise<Record<string, EffectiveField>> {
  const qs = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  return request<Record<string, EffectiveField>>(
    `/admin/apps/${applicationId}/effective-config${qs}`,
  )
}

export async function pinField(
  applicationId: string,
  payload: { tenant_id: string; field_path: string; version: number },
): Promise<void> {
  await request<void>(`/admin/apps/${applicationId}/field-pin`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function unpinField(
  applicationId: string,
  tenantId: string,
  fieldPath: string,
): Promise<void> {
  const qs = `?tenant_id=${encodeURIComponent(tenantId)}&field_path=${encodeURIComponent(fieldPath)}`
  await request<void>(`/admin/apps/${applicationId}/field-pin${qs}`, {
    method: 'DELETE',
  })
}

export async function setAppListing(applicationId: string, listed: boolean): Promise<void> {
  await request<void>(`/admin/apps/${applicationId}/listing`, {
    method: 'POST',
    body: JSON.stringify({ listed }),
  })
}

export async function setAppEnabled(applicationId: string, enabled: boolean): Promise<void> {
  await request<void>(`/admin/apps/${applicationId}/enabled`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

// ========== 数据可见范围 ==========
export interface AppVisibilityDepartment {
  department_id: string
  include_subtree: boolean
}

export interface AppVisibility {
  mode: 'all' | 'custom'
  departments: AppVisibilityDepartment[]
  users: string[]
}

export async function getAppVisibility(applicationId: string): Promise<AppVisibility> {
  return request<AppVisibility>(`/admin/apps/${applicationId}/visibility`)
}

export async function replaceAppVisibility(
  applicationId: string,
  payload: AppVisibility,
): Promise<AppVisibility> {
  return request<AppVisibility>(`/admin/apps/${applicationId}/visibility`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// ========== prompt 优化 ==========
export interface PromptOptimizeResult {
  optimized_prompt: string
  suggestions: string[]
}

export async function optimizePrompt(payload: {
  model_id: string
  current_prompt: string
  task_description?: string
}): Promise<PromptOptimizeResult> {
  return request<PromptOptimizeResult>('/admin/prompt-optimize', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// ========== 模型目录 ==========
export async function listAvailableModels(): Promise<ModelItem[]> {
  return request<ModelItem[]>('/admin/models/catalog/available')
}

export async function listModelCatalog(): Promise<ModelCatalogItem[]> {
  return request<ModelCatalogItem[]>('/admin/models/catalog')
}

export async function listProviders(): Promise<Provider[]> {
  return request<Provider[]>('/admin/models/providers')
}

// ========== 试运行 SSE ==========
export interface DebugNodeState {
  node_id: string
  type: string
  status: 'pending' | 'running' | 'success' | 'error'
  duration_ms: number
  output: Record<string, unknown>
  error: string
}

export interface DebugStreamEvent {
  event: 'node_start' | 'node_end' | 'result' | 'error' | 'interrupted'
  data: Record<string, unknown>
}

export interface ApprovalInterruptPayload {
  type: string
  node_id: string
  node_title?: string
  assignee_role?: string
  instructions?: string
  snapshot?: Record<string, unknown>
}

// ========== 结构校验（B10） ==========
export interface GraphValidationIssue {
  severity: 'error' | 'warning'
  code: string
  message: string
  node_id: string
}

export interface GraphValidationResult {
  valid: boolean
  issues: GraphValidationIssue[]
}

export async function validateGraph(graph: Graph): Promise<GraphValidationResult> {
  return request<GraphValidationResult>('/admin/apps/validate-graph', {
    method: 'POST',
    body: JSON.stringify({ graph }),
  })
}

/**
 * 画布试运行：SSE 逐节点推送 node_start / node_end / result / error / interrupted。
 * 复用 workflows 的 fetch + ReadableStream 手写 SSE 解析。
 */
export async function debugRunAppStream(
  payload: { graph: Graph; inputs: Record<string, unknown> },
  onEvent: (event: DebugStreamEvent) => void,
): Promise<void> {
  const response = await fetch('/api/v1/admin/apps/debug/run/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getAccessToken() ?? ''}`,
      ...(getTenantCode() ? { 'X-Tenant-Code': getTenantCode() } : {}),
    },
    body: JSON.stringify(payload),
  })
  if (!response.ok || !response.body) {
    throw new Error(`试运行启动失败：${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const eventLine = frame.split('\n').find((line) => line.startsWith('event:'))
      const dataLine = frame.split('\n').find((line) => line.startsWith('data:'))
      if (!eventLine || !dataLine) continue
      const event = eventLine.slice('event:'.length).trim()
      const dataRaw = dataLine.slice('data:'.length).trim()
      try {
        onEvent({ event: event as DebugStreamEvent['event'], data: JSON.parse(dataRaw) })
      } catch {
        // 忽略无法解析的帧
      }
    }
  }
}

async function _postSse(
  url: string,
  body: unknown,
  onEvent: (event: DebugStreamEvent) => void,
): Promise<void> {
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getAccessToken() ?? ''}`,
      ...(getTenantCode() ? { 'X-Tenant-Code': getTenantCode() } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!response.ok || !response.body) {
    throw new Error(`SSE 请求失败：${response.status}`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const eventLine = frame.split('\n').find((line) => line.startsWith('event:'))
      const dataLine = frame.split('\n').find((line) => line.startsWith('data:'))
      if (!eventLine || !dataLine) continue
      const event = eventLine.slice('event:'.length).trim()
      const dataRaw = dataLine.slice('data:'.length).trim()
      try {
        onEvent({ event: event as DebugStreamEvent['event'], data: JSON.parse(dataRaw) })
      } catch {
        // 忽略无法解析的帧
      }
    }
  }
}

/**
 * 人审续跑：从 interrupt 点继续 SSE 流。
 */
export async function debugRunAppStreamResume(
  payload: {
    graph: Graph
    thread_id: string
    run_id?: string
    approval: { approved: boolean; comment: string; approver: string }
  },
  onEvent: (event: DebugStreamEvent) => void,
): Promise<void> {
  return _postSse('/api/v1/admin/apps/debug/run/stream/resume', payload, onEvent)
}
