import { request } from './client'
import type {
  Employment,
  EmploymentArchivePayload,
  EmploymentCreatePayload,
  EmploymentTransferPayload,
  EmploymentUpdatePayload,
  PageResult,
} from './types'

export interface EmploymentListParams {
  page?: number
  page_size?: number
  keyword?: string
  department_id?: string
  user_id?: string
  is_current?: boolean
}

function buildQuery(params: EmploymentListParams): string {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.department_id) query.set('department_id', params.department_id)
  if (params.user_id) query.set('user_id', params.user_id)
  if (params.is_current !== undefined) query.set('is_current', String(params.is_current))
  return query.toString()
}

/** 用户任职记录：单一主任职，调岗归档旧记录并生成新当前记录。 */
export const employmentsApi = {
  async list(params: EmploymentListParams = {}): Promise<PageResult<Employment>> {
    return request<PageResult<Employment>>(`/admin/employments?${buildQuery(params)}`)
  },
  async create(payload: EmploymentCreatePayload): Promise<Employment> {
    return request<Employment>('/admin/employments', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: EmploymentUpdatePayload): Promise<Employment> {
    return request<Employment>(`/admin/employments/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async transfer(id: string, payload: EmploymentTransferPayload): Promise<Employment> {
    return request<Employment>(`/admin/employments/${id}/transfer`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async archive(id: string, payload: EmploymentArchivePayload = {}): Promise<Employment> {
    return request<Employment>(`/admin/employments/${id}/archive`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/employments/${id}`, { method: 'DELETE' })
  },
}
