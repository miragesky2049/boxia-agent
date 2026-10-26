import { request } from './client'

export interface MgmtUnit {
  id: string
  tenant_id: string
  parent_id: string | null
  name: string
  code: string | null
  path: string
  level: number
  sort_order: number
  attrs: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
  children?: MgmtUnit[]
}

export interface MgmtUnitCreatePayload {
  parent_id?: string | null
  name: string
  code?: string | null
  sort_order: number
  attrs?: Record<string, unknown>
}

export interface MgmtUnitUpdatePayload {
  parent_id?: string | null
  name: string
  code?: string | null
  sort_order: number
  attrs?: Record<string, unknown>
  is_active: boolean
}

export interface MgmtUnitDepartment {
  unit_id: string
  department_id: string
  include_subtree: boolean
}

export interface MgmtUnitUser {
  unit_id: string
  user_id: string
}

/** 管理单元 API：树形 CRUD + 部门/人员关联维护。 */
export const mgmtUnitsApi = {
  async tree(): Promise<MgmtUnit[]> {
    return request<MgmtUnit[]>('/admin/mgmt-units')
  },
  async active(): Promise<MgmtUnit[]> {
    return request<MgmtUnit[]>('/admin/mgmt-units/active')
  },
  async create(payload: MgmtUnitCreatePayload): Promise<MgmtUnit> {
    return request<MgmtUnit>('/admin/mgmt-units', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  async update(id: string, payload: MgmtUnitUpdatePayload): Promise<MgmtUnit> {
    return request<MgmtUnit>(`/admin/mgmt-units/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/mgmt-units/${id}`, { method: 'DELETE' })
  },
  async listDepartments(id: string): Promise<MgmtUnitDepartment[]> {
    return request<MgmtUnitDepartment[]>(`/admin/mgmt-units/${id}/departments`)
  },
  async replaceDepartments(
    id: string,
    bindings: Array<{ department_id: string; include_subtree: boolean }>,
  ): Promise<void> {
    await request<void>(`/admin/mgmt-units/${id}/departments`, {
      method: 'PUT',
      body: JSON.stringify({ bindings }),
    })
  },
  async listUsers(id: string): Promise<MgmtUnitUser[]> {
    return request<MgmtUnitUser[]>(`/admin/mgmt-units/${id}/users`)
  },
  async replaceUsers(id: string, user_ids: string[]): Promise<void> {
    await request<void>(`/admin/mgmt-units/${id}/users`, {
      method: 'PUT',
      body: JSON.stringify({ user_ids }),
    })
  },
}
