import { request } from './client'

export interface TenantSettings {
  default_model_catalog_id: string | null
  allowed_catalog_ids: string[]
  plugin_whitelist: string[]
  updated_at?: string | null
}

export async function getTenantSettings(tenantId: string): Promise<TenantSettings> {
  return request<TenantSettings>(`/admin/tenants/${tenantId}/settings`)
}

export async function updateTenantSettings(
  tenantId: string,
  payload: TenantSettings,
): Promise<TenantSettings> {
  return request<TenantSettings>(`/admin/tenants/${tenantId}/settings`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}
