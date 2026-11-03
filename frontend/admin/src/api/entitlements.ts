import { request } from './client'
import type { PageResult } from './types'

export type EntitlementObjectType = 'app' | 'tool' | 'skill' | 'prompt' | 'knowledge'

export type EntitlementMode = 'grant' | 'revoke'

export type EntitlementAuthType = 'FORMAL' | 'TRIAL' | 'GIFT'

export interface EntitlementItem {
  object_type: EntitlementObjectType
  object_id: string
}

/** 权益视图；status 为后端读侧按 [start_time, expire_time) 计算后的有效状态。 */
export interface EntitlementView {
  object_type: string
  object_id: string
  name: string
  status: string
  auth_source: string
  auth_type: string
  start_time: string | null
  expire_time: string | null
  quota: Record<string, unknown>
  remark: string
  granted_at: string | null
  is_deprecated: boolean
}

export interface RemovePreviewItem {
  view: EntitlementView
  affected_role_grants: number
  affected_role_names: string[]
}

export interface EntitlementPreview {
  add: EntitlementView[]
  remove: RemovePreviewItem[]
  unchanged: EntitlementView[]
}

export interface EntitlementFailedItem {
  object_type: string
  object_id: string
  reason: string
}

export interface EntitlementBatchPayload {
  tenant_id: string
  mode: EntitlementMode
  items: EntitlementItem[]
  reason?: string
  auth_type?: EntitlementAuthType
  start_time?: string | null
  expire_time?: string | null
}

export interface EntitlementBatchResult {
  updated: number
  failed: EntitlementFailedItem[]
  affected_role_grants: number
}

/** 对象反查：持有该权益的租户行。 */
export interface EntitlementTenantRow {
  tenant_id: string
  tenant_name: string
  status: string
  auth_source: string
  granted_at: string | null
}

export interface GrantApplicationPayload {
  tenant_id: string
  auth_type?: EntitlementAuthType
  contract_no?: string
  quota_json?: Record<string, unknown>
  /** OPS 直开必填，未来时间落 wait_effect。 */
  start_time: string
  expire_time?: string | null
  remark?: string
}

export async function listTenantEntitlements(
  tenantId: string,
  params: {
    object_type?: string
    status?: string
    keyword?: string
    page?: number
    page_size?: number
  } = {},
): Promise<PageResult<EntitlementView>> {
  const query = new URLSearchParams()
  if (params.object_type) query.set('object_type', params.object_type)
  if (params.status) query.set('status', params.status)
  if (params.keyword) query.set('keyword', params.keyword)
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  return request<PageResult<EntitlementView>>(
    `/admin/entitlements/tenants/${tenantId}?${query.toString()}`,
  )
}

export async function listObjectTenants(
  objectType: string,
  objectId: string,
  params: { page?: number; page_size?: number } = {},
): Promise<PageResult<EntitlementTenantRow>> {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  return request<PageResult<EntitlementTenantRow>>(
    `/admin/entitlements/objects/${objectType}/${objectId}/tenants?${query.toString()}`,
  )
}

export async function previewBatch(payload: EntitlementBatchPayload): Promise<EntitlementPreview> {
  return request<EntitlementPreview>('/admin/entitlements/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function applyBatch(
  payload: EntitlementBatchPayload,
): Promise<EntitlementBatchResult> {
  return request<EntitlementBatchResult>('/admin/entitlements/batch', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function grantApplication(
  applicationId: string,
  payload: GrantApplicationPayload,
): Promise<{ instance_id: string }> {
  return request<{ instance_id: string }>(
    `/admin/entitlements/applications/${applicationId}/grant`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  )
}
