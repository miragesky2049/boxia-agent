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

export interface TenantAgent {
  id: string
  name: string
  avatar_url: string
  description: string
  is_enabled: boolean
  is_opened: boolean
  opened_at: string | null
  opened_by: string | null
}

export interface TenantAgentOpenResult {
  agent_id: string
  tenant_id: string
  is_opened: boolean
  opened_at: string | null
}

export interface TenantAgentBatchOpenResult {
  tenant_id: string
  opened: boolean
  count: number
  agent_ids: string[]
}

export interface AgentOpenedTenant {
  id: string
  code: string
  name: string
  is_active: boolean
  opened_at: string
  opened_by: string | null
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

export type PermissionCategory =
  | 'system'
  | 'menu'
  | 'page'
  | 'button'
  | 'agent'
  | 'skill'
  | 'tool'
  | 'component'
  | 'prompt'

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
  role_id: string
  role_ids: string[]
  current_department_id: string | null
  current_department_name: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
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
  user_name: string | null
  user_display_name: string | null
  department_name: string | null
  department_path: string | null
  created_at: string
  updated_at: string
}

export interface EmploymentCreatePayload {
  user_id: string
  department_id: string
  position?: string
  started_at?: string
}

export interface EmploymentUpdatePayload {
  position?: string
  started_at?: string
}

export interface EmploymentTransferPayload {
  department_id: string
  position?: string
  started_at?: string
}

export interface UserCreatePayload {
  username: string
  password: string
  display_name: string
  role_ids: string[]
  is_active: boolean
}

export interface UserUpdatePayload {
  display_name?: string
  role_ids?: string[]
  is_active?: boolean
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

export type ResourceType = 'agent' | 'skill' | 'tool' | 'component' | 'prompt'

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
}

export interface RoleGrantSummary {
  counts: Record<string, number>
}

export interface UserRoleAssignPayload {
  user_ids: string[]
  role_ids: string[]
  mgmt_unit_ids: string[]
  tenant_id?: string | null
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

export interface ResourceBase {
  id: string
  name: string
  description: string
  is_enabled: boolean
  tenant_id: string | null
  agent_id: string | null
  is_platform: boolean
  created_at: string
  updated_at: string
}

export interface Skill extends ResourceBase {
  content: string
  config: Record<string, unknown>
}

export interface SkillFileMeta {
  path: string
  size_bytes: number
  content_hash: string
  media_type: string
  updated_at: string
}

export interface SkillFile extends SkillFileMeta {
  content: string
}

export interface SkillFileList {
  items: SkillFileMeta[]
  total: number
  total_bytes: number
}

export interface SkillFileWritePayload {
  path: string
  content: string
  expected_hash?: string
}

export interface Tool extends ResourceBase {
  type: string
  config: Record<string, unknown>
}

export interface ComponentResource extends ResourceBase {
  type: string
  config: Record<string, unknown>
}

export interface PromptResource extends ResourceBase {
  content: string
  variables: string[]
  category: string
}

export interface FaqItem {
  question: string
  answer: string
}

export interface ModelSettings {
  model: string
  temperature: number
  max_output_tokens: number
  reasoning_effort: string
  context_window: number
  max_thinking_tokens: number
}

export interface PromptSettings {
  role_setting: string
  persona: string
  user_prompt: string
  memory_count: number
  memory_model: string
}

export interface MemorySettings {
  enabled: boolean
  task_memory_prompt: string
  long_term_enabled: boolean
  long_term_prompt: string
}

export interface ConversationSettings {
  welcome: string
  fallback: string
  input_placeholder: string
  common_questions_enabled: boolean
  faqs: FaqItem[]
}

export interface ChannelSettings {
  type: string
  enabled: boolean
}

export interface KnowledgeSettings {
  enabled: boolean
  dataset_ids: string[]
}

export interface OtherSettings {
  system_prompt_template: string
  max_turns: number
  deep_thinking: boolean
  show_reasoning: boolean
  web_search: boolean
  create_task: boolean
  history_task: boolean
  scheduled_task: boolean
  artifacts: boolean
  upload_attachment: boolean
  upload_file_types: string[]
  upload_max_size_mb: number
  task_list: boolean
}

export interface AgentConfig {
  model: ModelSettings
  prompt: PromptSettings
  memory: MemorySettings
  conversation: ConversationSettings
  channel: ChannelSettings
  knowledge: KnowledgeSettings
  other: OtherSettings
  extensions: Record<string, string | null>
}

export interface AgentSummary extends ResourceBase {
  avatar_url: string
  department_id?: string | null
}

export interface Agent extends AgentSummary {
  config: AgentConfig
  tool_ids: string[]
  skill_ids: string[]
}

export interface AgentPayload {
  name: string
  avatar_url: string
  description: string
  is_enabled: boolean
  config: AgentConfig
  tool_ids: string[]
  skill_ids: string[]
  department_id?: string | null
}

export interface ListParams {
  page?: number
  page_size?: number
  keyword?: string
  is_enabled?: boolean
  agent_id?: string
}

export interface SkillPayload {
  name: string
  description: string
  is_enabled: boolean
  content: string
  config: Record<string, unknown>
  agent_id?: string | null
}

export interface ToolPayload {
  name: string
  description: string
  is_enabled: boolean
  type: string
  config: Record<string, unknown>
  agent_id?: string | null
}

export interface ComponentPayload {
  name: string
  description: string
  is_enabled: boolean
  type: string
  config: Record<string, unknown>
  agent_id?: string | null
}

export interface PromptPayload {
  name: string
  description: string
  is_enabled: boolean
  content: string
  variables: string[]
  category: string
  agent_id?: string | null
}
