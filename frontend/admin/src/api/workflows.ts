import { request } from './client'
import type { PageResult } from './types'

export type WorkflowGraphNodeType = 'start' | 'llm' | 'tool' | 'end'

export interface WorkflowGraphNode {
  id: string
  type: WorkflowGraphNodeType
  position?: { x: number; y: number }
  data?: Record<string, unknown>
}

export interface WorkflowGraphEdge {
  source: string
  target: string
}

export interface WorkflowGraph {
  variables?: Array<{ key: string; type: string; required?: boolean; default?: unknown }>
  nodes: WorkflowGraphNode[]
  edges: WorkflowGraphEdge[]
}

export interface WorkflowSummary {
  id: string
  tenant_id: string
  name: string
  description: string
  is_enabled: boolean
  visibility_mode: 'all' | 'custom'
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface Workflow extends WorkflowSummary {
  graph: WorkflowGraph
}

export interface WorkflowPayload {
  name: string
  description?: string
  graph: WorkflowGraph
  is_enabled?: boolean
  visibility_mode?: 'all' | 'custom'
}

export interface WorkflowTemplate {
  id: string
  tenant_id: string
  name: string
  description: string
  graph: WorkflowGraph
  category: string
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export interface WorkflowTemplatePayload {
  name: string
  description?: string
  graph: WorkflowGraph
  category?: string
  is_enabled?: boolean
}

export interface GraphValidateResult {
  valid: boolean
  node_count: number
  edge_count: number
  node_types: string[]
}

const PLATFORM_TENANT_ID = '00000000-0000-0000-0000-000000000000'

export function isPlatformTenant(tenantId: string | null | undefined): boolean {
  return tenantId === PLATFORM_TENANT_ID
}

export async function listWorkflows(params: {
  page?: number
  page_size?: number
  keyword?: string
  is_enabled?: boolean
} = {}): Promise<PageResult<WorkflowSummary>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled))
  return request<PageResult<WorkflowSummary>>(`/admin/workflows?${query.toString()}`)
}

export async function getWorkflow(id: string): Promise<Workflow> {
  return request<Workflow>(`/admin/workflows/${id}`)
}

export async function createWorkflow(payload: WorkflowPayload): Promise<Workflow> {
  return request<Workflow>('/admin/workflows', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateWorkflow(
  id: string,
  payload: WorkflowPayload,
): Promise<Workflow> {
  return request<Workflow>(`/admin/workflows/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteWorkflow(id: string): Promise<void> {
  await request<void>(`/admin/workflows/${id}`, { method: 'DELETE' })
}

export async function validateGraph(
  payload: WorkflowPayload,
): Promise<GraphValidateResult> {
  return request<GraphValidateResult>('/admin/workflows/validate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function listTemplates(params: {
  page?: number
  page_size?: number
  keyword?: string
  category?: string
} = {}): Promise<PageResult<WorkflowTemplate>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.category) query.set('category', params.category)
  return request<PageResult<WorkflowTemplate>>(`/admin/workflows/templates?${query.toString()}`)
}

export async function getTemplate(id: string): Promise<WorkflowTemplate> {
  return request<WorkflowTemplate>(`/admin/workflows/templates/${id}`)
}

export async function createTemplate(
  payload: WorkflowTemplatePayload,
): Promise<WorkflowTemplate> {
  return request<WorkflowTemplate>('/admin/workflows/templates', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateTemplate(
  id: string,
  payload: WorkflowTemplatePayload,
): Promise<WorkflowTemplate> {
  return request<WorkflowTemplate>(`/admin/workflows/templates/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deleteTemplate(id: string): Promise<void> {
  await request<void>(`/admin/workflows/templates/${id}`, { method: 'DELETE' })
}

export async function cloneWorkflowFromTemplate(
  templateId: string,
  payload: { name: string; description?: string | null },
): Promise<Workflow> {
  return request<Workflow>(`/admin/workflows/clone-from-template/${templateId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
