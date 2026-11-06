import { request } from './client'

// 可见范围 v2（0068）：租户侧对已订阅产品级应用的可见范围配置

export type VisibilitySubjectType = 'DEPARTMENT' | 'ROLE' | 'USER'

export interface WhitelistItem {
  subject_type: VisibilitySubjectType
  subject_id: string
  include_subtree: boolean
}

export interface TenantVisibility {
  configured: boolean
  visibility: 'all' | 'whitelist'
  whitelist: WhitelistItem[]
  visibility_lock: boolean
  // 当前用户是否在管理范围内（false 时详情页只读）
  manageable?: boolean
}

export interface SubscribedApp {
  id: string
  name: string
  avatar_url: string
  description: string
  visibility_lock: boolean
  visibility_template: 'all' | 'whitelist'
  admin_scope_mode?: 'creator_only' | 'mgmt_unit' | 'all_admin'
  // 当前用户按管理范围能否管理该应用
  manageable?: boolean
  configured: boolean
  visibility: 'all' | 'whitelist'
  whitelist_count: number
}

export interface AdminScope {
  mgmt_unit_id: string
  mgmt_unit_name: string
  mgmt_unit_code: string | null
}

/** 当前租户已订阅（生效中）的产品级应用列表；scope=managed 只返回我可管理的。 */
export async function listSubscribedApps(scope?: 'all' | 'managed'): Promise<SubscribedApp[]> {
  const suffix = scope && scope !== 'all' ? `?scope=${scope}` : ''
  return request<SubscribedApp[]>(`/admin/tenant/apps${suffix}`)
}

export async function getTenantVisibility(applicationId: string): Promise<TenantVisibility> {
  return request<TenantVisibility>(`/admin/tenant/apps/${applicationId}/visibility`)
}

export async function putTenantVisibility(
  applicationId: string,
  payload: { visibility: 'all' | 'whitelist'; whitelist: WhitelistItem[] },
): Promise<TenantVisibility> {
  return request<TenantVisibility>(`/admin/tenant/apps/${applicationId}/visibility`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// 管理范围（0069 二期）：应用 ↔ 管理单元关联

export async function listAdminScopes(applicationId: string): Promise<AdminScope[]> {
  return request<AdminScope[]>(`/admin/tenant/apps/${applicationId}/admin-scope`)
}

export async function addAdminScope(applicationId: string, mgmtUnitId: string): Promise<void> {
  await request(`/admin/tenant/apps/${applicationId}/admin-scope`, {
    method: 'POST',
    body: JSON.stringify({ mgmt_unit_id: mgmtUnitId }),
  })
}

export async function removeAdminScope(applicationId: string, mgmtUnitId: string): Promise<void> {
  await request(`/admin/tenant/apps/${applicationId}/admin-scope/${mgmtUnitId}`, {
    method: 'DELETE',
  })
}
