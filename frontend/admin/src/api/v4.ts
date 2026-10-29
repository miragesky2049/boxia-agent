import { request } from './client'
import { getAccessToken } from '../auth/tokenStore'
import { getTenantCode } from '../tenant/scope'

// ========== 应用 graph ==========
export interface V4GraphNode {
  id: string
  type: string
  position?: { x: number; y: number }
  config?: Record<string, unknown>
}

export interface V4GraphEdge {
  from: string
  to: string
  type?: 'normal' | 'feedback'
  when?: string
}

export interface V4Graph {
  nodes: V4GraphNode[]
  edges: V4GraphEdge[]
}

export interface V4Application {
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

export interface V4ApplicationGraph extends V4Application {
  graph: V4Graph
  runtime_mode: 'dag' | 'agent_loop'
}

export interface V4MarketplaceItem {
  id: string
  name: string
  avatar_url: string | null
  description: string
}

export interface V4MyApp {
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
export interface V4ModelItem {
  model_id: string
  display_name: string
  capabilities: Record<string, unknown>
  provider_name: string
}

export interface V4ModelCatalogItem extends V4ModelItem {
  id: string
  provider_id: string
  is_enabled: boolean
  base_url: string
}

export interface V4Provider {
  id: string
  name: string
  base_url: string
  owner_type: 'platform' | 'tenant'
  owner_id: string | null
  is_enabled: boolean
  created_at: string
}

// ========== 市场接口（租户端） ==========
export async function listMarketplace(): Promise<V4MarketplaceItem[]> {
  return request<V4MarketplaceItem[]>('/admin/v4/marketplace/applications')
}

export async function subscribeApplication(applicationId: string): Promise<{
  instance_id: string
  application_id: string
}> {
  return request<{ instance_id: string; application_id: string }>(
    '/admin/v4/marketplace/subscribe',
    {
      method: 'POST',
      body: JSON.stringify({ application_id: applicationId }),
    },
  )
}

export async function listMyApps(): Promise<V4MyApp[]> {
  return request<V4MyApp[]>('/admin/v4/marketplace/my-apps')
}

// ========== 运行历史 ==========
export interface V4RunItem {
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

export interface V4NodeExecution {
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

export interface V4RunDetail {
  run: V4RunItem & {
    tenant_id: string
  }
  node_executions: V4NodeExecution[]
}

export async function listApplicationRuns(
  applicationId: string,
  limit = 50,
): Promise<V4RunItem[]> {
  return request<V4RunItem[]>(
    `/admin/v4/marketplace/applications/${applicationId}/runs?limit=${limit}`,
  )
}

export async function getRunDetail(runId: string): Promise<V4RunDetail> {
  return request<V4RunDetail>(`/admin/v4/marketplace/runs/${runId}`)
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
  }>(`/admin/v4/marketplace/applications/${applicationId}/runs/${threadId}/resume`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export type V4RunResult = {
  status: 'success' | 'waiting_approval'
  output?: Record<string, unknown>
  thread_id: string
  run_id: string
  approval?: Record<string, unknown>
}

export async function runApplication(
  applicationId: string,
  inputs: Record<string, unknown>,
): Promise<V4RunResult> {
  return request<V4RunResult>(`/admin/v4/marketplace/applications/${applicationId}/run`, {
    method: 'POST',
    body: JSON.stringify({ inputs }),
  })
}

// ========== 统一资源（tool / prompt / skill / knowledge） ==========
export type V4ResourceType = 'tool' | 'prompt' | 'skill' | 'knowledge'

export interface V4Resource {
  id: string
  type: V4ResourceType
  owner_type: 'platform' | 'tenant'
  owner_id: string | null
  name: string
  config: Record<string, unknown>
  version: number
  is_enabled: boolean
  is_deprecated: boolean
  created_at: string
}

export interface V4ResourceGrant {
  id: string
  resource_id: string
  tenant_id: string
  granted_at: string
}

export async function listResources(params: {
  type?: V4ResourceType
  owner_type?: 'platform' | 'tenant'
} = {}): Promise<V4Resource[]> {
  const query = new URLSearchParams()
  if (params.type) query.set('type', params.type)
  if (params.owner_type) query.set('owner_type', params.owner_type)
  const qs = query.toString()
  return request<V4Resource[]>(`/admin/v4/resources${qs ? `?${qs}` : ''}`)
}

export async function getResource(resourceId: string): Promise<V4Resource> {
  return request<V4Resource>(`/admin/v4/resources/${resourceId}`)
}

export async function createResource(payload: {
  type: V4ResourceType
  name: string
  config: Record<string, unknown>
}): Promise<{ resource_id: string }> {
  return request<{ resource_id: string }>('/admin/v4/resources', {
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
  await request<void>(`/admin/v4/resources/${resourceId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function deleteResource(resourceId: string): Promise<void> {
  await request<void>(`/admin/v4/resources/${resourceId}`, { method: 'DELETE' })
}

export async function listResourceGrants(resourceId: string): Promise<V4ResourceGrant[]> {
  return request<V4ResourceGrant[]>(`/admin/v4/resources/${resourceId}/grants`)
}

export async function grantResource(
  resourceId: string,
  tenantId: string,
): Promise<void> {
  await request<void>(`/admin/v4/resources/${resourceId}/grants`, {
    method: 'POST',
    body: JSON.stringify({ tenant_id: tenantId }),
  })
}

export async function revokeResourceGrant(
  resourceId: string,
  tenantId: string,
): Promise<void> {
  await request<void>(`/admin/v4/resources/${resourceId}/grants/${tenantId}`, {
    method: 'DELETE',
  })
}

// ========== 平台应用管理 ==========
export async function listApps(params: {
  owner_type?: string
  marketplace_only?: boolean
} = {}): Promise<V4Application[]> {
  const query = new URLSearchParams()
  if (params.owner_type) query.set('owner_type', params.owner_type)
  if (params.marketplace_only) query.set('marketplace_only', 'true')
  const qs = query.toString()
  return request<V4Application[]>(`/admin/v4/apps${qs ? `?${qs}` : ''}`)
}

export async function createApp(payload: {
  name: string
  description?: string
}): Promise<{ application_id: string }> {
  return request<{ application_id: string }>('/admin/v4/apps', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function getApp(applicationId: string): Promise<V4Application> {
  return request<V4Application>(`/admin/v4/apps/${applicationId}`)
}

export async function updateApp(
  applicationId: string,
  payload: { name?: string; description?: string; avatar_url?: string | null },
): Promise<void> {
  await request<void>(`/admin/v4/apps/${applicationId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function getAppGraph(applicationId: string): Promise<{
  graph: V4Graph
  runtime_mode: 'dag' | 'agent_loop'
  graph_schema_version: number
}> {
  return request<{ graph: V4Graph; runtime_mode: 'dag' | 'agent_loop'; graph_schema_version: number }>(
    `/admin/v4/apps/${applicationId}/graph`,
  )
}

export async function saveAppGraph(
  applicationId: string,
  graph: V4Graph,
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
  }>(`/admin/v4/apps/${applicationId}/graph`, {
    method: 'PUT',
    body: JSON.stringify({ graph }),
  })
}

// ========== 字段级版本 ==========
export interface V4FieldVersion {
  field_path: string
  version: number
  value: unknown
  changelog: string
  published_at: string | null
  created_at: string
}

export interface V4EffectiveField {
  version: number
  value: unknown
  pinned: boolean
}

export interface V4FieldPin {
  field_path: string
  pinned_version: number
  created_at: string
}

export async function listFieldVersions(
  applicationId: string,
  fieldPath?: string,
): Promise<V4FieldVersion[]> {
  const qs = fieldPath ? `?field_path=${encodeURIComponent(fieldPath)}` : ''
  return request<V4FieldVersion[]>(`/admin/v4/apps/${applicationId}/field-versions${qs}`)
}

export async function getEffectiveConfig(
  applicationId: string,
  tenantId?: string,
): Promise<Record<string, V4EffectiveField>> {
  const qs = tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ''
  return request<Record<string, V4EffectiveField>>(
    `/admin/v4/apps/${applicationId}/effective-config${qs}`,
  )
}

export async function pinField(
  applicationId: string,
  payload: { tenant_id: string; field_path: string; version: number },
): Promise<void> {
  await request<void>(`/admin/v4/apps/${applicationId}/field-pin`, {
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
  await request<void>(`/admin/v4/apps/${applicationId}/field-pin${qs}`, {
    method: 'DELETE',
  })
}

export async function setAppListing(applicationId: string, listed: boolean): Promise<void> {
  await request<void>(`/admin/v4/apps/${applicationId}/listing`, {
    method: 'POST',
    body: JSON.stringify({ listed }),
  })
}

export async function setAppEnabled(applicationId: string, enabled: boolean): Promise<void> {
  await request<void>(`/admin/v4/apps/${applicationId}/enabled`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

// ========== 模型目录 ==========
export async function listAvailableModels(): Promise<V4ModelItem[]> {
  return request<V4ModelItem[]>('/admin/v4/models/catalog/available')
}

export async function listModelCatalog(): Promise<V4ModelCatalogItem[]> {
  return request<V4ModelCatalogItem[]>('/admin/v4/models/catalog')
}

export async function listProviders(): Promise<V4Provider[]> {
  return request<V4Provider[]>('/admin/v4/models/providers')
}

// ========== 试运行 SSE ==========
export interface V4DebugNodeState {
  node_id: string
  type: string
  status: 'pending' | 'running' | 'success' | 'error'
  duration_ms: number
  output: Record<string, unknown>
  error: string
}

export interface V4DebugStreamEvent {
  event: 'node_start' | 'node_end' | 'result' | 'error'
  data: Record<string, unknown>
}

/**
 * v4 画布试运行：SSE 逐节点推送 node_start / node_end / result / error。
 * 复用 workflows 的 fetch + ReadableStream 手写 SSE 解析。
 */
export async function debugRunAppStream(
  payload: { graph: V4Graph; inputs: Record<string, unknown> },
  onEvent: (event: V4DebugStreamEvent) => void,
): Promise<void> {
  const response = await fetch('/api/v1/admin/v4/apps/debug/run/stream', {
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
        onEvent({ event: event as V4DebugStreamEvent['event'], data: JSON.parse(dataRaw) })
      } catch {
        // 忽略无法解析的帧
      }
    }
  }
}
