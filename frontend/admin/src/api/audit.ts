import { request } from './client'

export interface AuditLogItem {
  id: string
  actor_id: string | null
  actor_username: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  request_id: string | null
  ip: string | null
  user_agent: string | null
  detail: Record<string, unknown>
  tenant_id: string | null
  created_at: string
}

export interface AuditLogPage {
  items: AuditLogItem[]
  total: number
  page: number
  page_size: number
}

export async function listAuditLogs(params: {
  page?: number
  page_size?: number
  action?: string
  actor_id?: string
}): Promise<AuditLogPage> {
  const query = new URLSearchParams()
  if (params.page) query.set('page', String(params.page))
  if (params.page_size) query.set('page_size', String(params.page_size))
  if (params.action) query.set('action', params.action)
  if (params.actor_id) query.set('actor_id', params.actor_id)
  const qs = query.toString()
  return request<AuditLogPage>(`/admin/audit-logs${qs ? `?${qs}` : ''}`)
}
