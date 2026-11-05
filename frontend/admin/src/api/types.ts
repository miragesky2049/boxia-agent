export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type Scope = 'platform' | 'tenant'

export type AppEnv = 'local' | 'dev' | 'test' | 'prod'

export type TenantResolution = 'host' | 'header' | 'default'

export type TenantSwitchMode = 'none' | 'header' | 'host'

export interface Tenant {
  id: string
  code: string
  name: string
  is_active: boolean
  created_at: string
  updated_at: string
  is_platform?: boolean
}

export interface TenantDeleteResult {
  tenant_id: string
  code: string
  audit_id: string
  deleted: Record<string, number>
}

export interface TenantBatchDeleteItem {
  tenant_id: string
  code: string | null
  success: boolean
  audit_id: string | null
  error_code: string | null
  error: string | null
}

export interface TenantBatchDeleteResult {
  total: number
  succeeded: number
  failed: number
  items: TenantBatchDeleteItem[]
}

export interface PasswordPolicy {
  min_length: number
  max_bytes: number
  min_categories: number
}

export interface PublicContext {
  scope: Scope
  tenant: Tenant | null
  app_env: AppEnv
  tenant_resolution: TenantResolution
  tenant_switch_mode: TenantSwitchMode
  root_domain: string
  platform_admin_subdomain: string
  platform_admin_host: string
  platform_name: string
  password_policy: PasswordPolicy
}

export interface AdminContext {
  scope: Scope
  tenant: Tenant | null
  user: AdminUser
  role_code: string
  role_name: string
  permissions: string[]
  menus: string[]
  app_env: AppEnv
  tenant_resolution: TenantResolution
  tenant_switch_mode: TenantSwitchMode
  root_domain: string
  platform_admin_subdomain: string
  platform_admin_host: string
  platform_name: string
  password_policy: PasswordPolicy
}

export interface TenantCreatePayload {
  code: string
  name: string
  admin_username: string
  admin_password: string
  admin_display_name?: string
}

export interface TenantUpdatePayload {
  name?: string
  is_active?: boolean
}

export interface AdminUser {
  id: string
  username: string
  display_name: string
  role_id: string | null
  role_code: string
  role_name: string
  is_active: boolean
  must_change_password: boolean
  tenant_id: string | null
  is_platform: boolean
  created_at: string
  updated_at: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
  refresh_expires_in: number
  user: AdminUser
}

export interface AdminUserCreatePayload {
  username: string
  password: string
  display_name: string
  role_id: string
}

export interface AdminUserUpdatePayload {
  display_name?: string
  role_id?: string
  is_active?: boolean
}

export interface Role {
  id: string
  tenant_id: string | null
  code: string
  name: string
  description: string
  is_system: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface RoleCreatePayload {
  code: string
  name: string
  description?: string
}

export interface RoleUpdatePayload {
  name?: string
  description?: string
  is_active?: boolean
}

export interface RoleCopyPayload {
  code: string
  name: string
  description?: string
}

export type PermissionCategory = 'system' | 'menu' | 'page' | 'button' | 'tool'

export interface PermissionResource {
  id: string
  code: string
  name: string
  category: PermissionCategory
  action: string
  description: string
  sort_order: number
}

export interface RolePermissionList {
  items: PermissionResource[]
  codes: string[]
}

export interface User {
  id: string
  tenant_id: string
  username: string
  display_name: string
  is_active: boolean
  role_id: string | null
  role_ids: string[]
  current_department_id: string | null
  current_department_name: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
  // HR 基础字段
  employee_no: string | null
  phone: string | null
  email: string | null
  gender: string | null
  birth_date: string | null
  avatar_url: string
  remark: string
  // 用户被授权的管理单元
  mgmt_unit_ids: string[]
  mgmt_unit_names: string[]
}

export interface UserOption {
  id: string
  username: string
  display_name: string
  is_active: boolean
}

export interface Department {
  id: string
  tenant_id: string
  parent_id: string | null
  name: string
  code: string | null
  path: string
  level: number
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
  children?: Department[]
}

export interface DepartmentCreatePayload {
  parent_id?: string | null
  name: string
  code?: string | null
  sort_order: number
  is_active?: boolean
}

export interface DepartmentUpdatePayload {
  parent_id?: string | null
  name: string
  code?: string | null
  sort_order: number
}

export interface Employment {
  id: string
  tenant_id: string
  user_id: string
  department_id: string
  position: string
  is_current: boolean
  started_at: string
  ended_at: string | null
  // HR 字典外键
  employment_type_id: string | null
  job_level_id: string | null
  job_family_id: string | null
  manager_id: string | null
  // 用工基础信息
  work_location: string | null
  cost_center: string | null
  contract_no: string | null
  weekly_hours: number | null
  employment_nature: string | null
  // 试用期与转正
  probation_started_at: string | null
  probation_ended_at: string | null
  regularized_at: string | null
  // 变动与离职
  change_type: string | null
  change_reason: string | null
  termination_type: string | null
  remark: string
  // 展示字段
  user_name: string | null
  user_display_name: string | null
  department_name: string | null
  department_path: string | null
  manager_name: string | null
  employment_type_name: string | null
  job_level_name: string | null
  job_family_name: string | null
  created_at: string
  updated_at: string
}

export interface HrFieldsPayload {
  employment_type_id?: string | null
  job_level_id?: string | null
  job_family_id?: string | null
  manager_id?: string | null
  work_location?: string | null
  cost_center?: string | null
  contract_no?: string | null
  weekly_hours?: number | null
  employment_nature?: string | null
  probation_started_at?: string | null
  probation_ended_at?: string | null
  regularized_at?: string | null
  change_reason?: string | null
  remark?: string | null
}

export interface EmploymentCreatePayload extends HrFieldsPayload {
  user_id: string
  department_id: string
  position?: string
  started_at?: string
}

export interface EmploymentUpdatePayload extends HrFieldsPayload {
  position?: string
  started_at?: string
}

export interface EmploymentTransferPayload extends HrFieldsPayload {
  department_id: string
  position?: string
  started_at?: string
  change_type?: string
}

export interface EmploymentArchivePayload {
  ended_at?: string | null
  termination_type?: string | null
  change_reason?: string | null
}

export interface HrDictionary {
  id: string
  tenant_id: string
  category: 'employment_type' | 'job_level' | 'job_family'
  code: string
  name: string
  sort_order: number
  is_active: boolean
  remark: string
  created_at: string
  updated_at: string
}

export interface HrDictionaryCreatePayload {
  category: HrDictionary['category']
  code: string
  name: string
  sort_order: number
  remark?: string
}

export interface HrDictionaryUpdatePayload {
  name?: string
  sort_order?: number
  is_active?: boolean
  remark?: string
}

export interface UserCreatePayload {
  username: string
  password: string
  display_name: string
  // 角色授权统一在「用户授权」页面维护
  role_ids?: string[]
  is_active: boolean
  // HR 基础字段
  employee_no?: string | null
  phone?: string | null
  email?: string | null
  gender?: string | null
  birth_date?: string | null
  avatar_url?: string
  remark?: string
}

export interface UserUpdatePayload {
  display_name?: string
  role_ids?: string[]
  is_active?: boolean
  // HR 基础字段
  employee_no?: string | null
  phone?: string | null
  email?: string | null
  gender?: string | null
  birth_date?: string | null
  avatar_url?: string
  remark?: string
}

export interface ResourceGrant {
  id: string
  resource_type: ResourceType
  resource_id: string
  tenant_id: string | null
  role_id: string | null
  granted_by: string | null
  created_at: string
}

export type ResourceType = 'tool' | 'skill' | 'prompt' | 'knowledge' | 'app'

export type GrantBatchMode = 'merge' | 'replace' | 'clear'

export interface GrantBatchPayload {
  resource_type: ResourceType
  resource_ids: string[]
  mode: GrantBatchMode
  tenant_id?: string | null
  role_ids: string[]
}

export interface RoleGrantResource {
  resource_id: string
  name: string
  description: string
  is_platform: boolean
  is_enabled: boolean
  updated_at: string
  is_granted: boolean
  /** tenant 档整租户授权（全员可见），仅租户角色可能为 true。 */
  is_tenant_wide?: boolean
}

export interface RoleGrantSummary {
  counts: Record<string, number>
}

export type UserRoleAssignMode = 'append' | 'replace'

export interface UserRoleAssignPayload {
  user_ids: string[]
  role_ids: string[]
  mgmt_unit_ids: string[]
  tenant_id?: string | null
  /** append=追加（默认）；replace=整体覆盖每个目标用户的角色与管理单元。 */
  mode?: UserRoleAssignMode
}

export interface AuditLog {
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
  created_at: string
}
