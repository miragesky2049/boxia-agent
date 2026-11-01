import { request } from './client'

export interface ModelCatalogItem {
  model_id: string
  display_name: string
  provider_name: string
  capabilities: {
    default_temperature?: number
    default_max_tokens?: number
    supports_tools?: boolean
    context_window?: number
    [key: string]: unknown
  }
}

export async function listAvailableModels(): Promise<ModelCatalogItem[]> {
  return request<ModelCatalogItem[]>('/admin/models/catalog/available')
}
