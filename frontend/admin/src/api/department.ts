import { request } from './client'
import type { Department, DepartmentCreatePayload, DepartmentUpdatePayload } from './types'

/** 租户内部门管理：物化路径树，最多 10 级。 */
export const departmentsApi = {
  async tree(): Promise<Department[]> {
    return request<Department[]>('/admin/departments')
  },
  async create(payload: DepartmentCreatePayload): Promise<Department> {
    return request<Department>('/admin/departments', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: DepartmentUpdatePayload): Promise<Department> {
    return request<Department>(`/admin/departments/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async setActive(id: string, isActive: boolean): Promise<Department> {
    return request<Department>(`/admin/departments/${id}/status`, {
      method: 'POST',
      body: JSON.stringify({ is_active: isActive }),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/departments/${id}`, { method: 'DELETE' })
  },
}
