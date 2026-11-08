import { request } from './client'
import type { HrDictionary, HrDictionaryCreatePayload, HrDictionaryUpdatePayload } from './types'

export type HrDictionaryCategory = 'employment_type' | 'job_level' | 'job_family'

/** HR 字典：雇佣类型 / 岗位职级 / 岗位序列，租户级维护。 */
export const hrDictionariesApi = {
  async list(category: HrDictionaryCategory, includeInactive = false): Promise<HrDictionary[]> {
    const query = new URLSearchParams()
    query.set('category', category)
    if (includeInactive) query.set('include_inactive', 'true')
    return request<HrDictionary[]>(`/admin/hr-dictionaries?${query.toString()}`)
  },
  async create(payload: HrDictionaryCreatePayload): Promise<HrDictionary> {
    return request<HrDictionary>('/admin/hr-dictionaries', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: HrDictionaryUpdatePayload): Promise<HrDictionary> {
    return request<HrDictionary>(`/admin/hr-dictionaries/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/hr-dictionaries/${id}`, { method: 'DELETE' })
  },
}
