export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export type AdminRole = 'superadmin' | 'admin' | 'viewer'

export type Scope = 'platform' | 'tenant'

export type AppEnv = 'local' | 'dev' | 'test' | 'prod'

export type TenantResolution = 'host' | 'header' | 'default'

export type TenantSwitchMode = 'none' | 'header' | 'host'

export interface Tenant {
  id: number
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
  role: AdminRole
  system_role: AdminRole
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
  id: number
  username: string
  display_name: string
  role: AdminRole
  role_id: number | null
  is_active: boolean
  must_change_password: boolean
  tenant_id: number | null
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
  role: AdminRole
  role_id?: number | null
}

export interface AdminUserUpdatePayload {
  display_name?: string
  role?: AdminRole
  role_id?: number | null
  is_active?: boolean
}

export interface Role {
  id: number
  tenant_id: number
  code: string
  name: string
  description: string
  system_role: AdminRole
  is_system: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface RoleCreatePayload {
  code: string
  name: string
  description?: string
  system_role: AdminRole
}

export interface RoleUpdatePayload {
  name?: string
  description?: string
  system_role?: AdminRole
  is_active?: boolean
}

export interface User {
  id: number
  tenant_id: number
  username: string
  display_name: string
  is_active: boolean
  role_id: number
  role_ids: number[]
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export interface UserCreatePayload {
  username: string
  password: string
  display_name: string
  role_ids: number[]
  is_active: boolean
}

export interface UserUpdatePayload {
  display_name?: string
  role_ids?: number[]
  is_active?: boolean
}

export interface ResourceGrant {
  id: number
  resource_type: ResourceType
  resource_id: number
  tenant_id: number
  role_id: number | null
  granted_by: number | null
  created_at: string
}

export type ResourceType = 'agent' | 'skill' | 'tool' | 'component' | 'prompt'

export type GrantBatchMode = 'merge' | 'replace' | 'clear'

export interface GrantBatchPayload {
  resource_type: ResourceType
  resource_ids: number[]
  mode: GrantBatchMode
  tenant_id?: number | null
  role_ids: number[]
}

export interface RoleGrantResource {
  resource_id: number
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
  user_ids: number[]
  role_ids: number[]
  tenant_id?: number | null
}

export interface AuditLog {
  id: number
  actor_id: number | null
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
  id: number
  name: string
  description: string
  is_enabled: boolean
  tenant_id: number | null
  agent_id: number | null
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
  extensions: Record<string, number | null>
}

export interface AgentSummary extends ResourceBase {
  avatar_url: string
}

export interface Agent extends AgentSummary {
  config: AgentConfig
  tool_ids: number[]
  skill_ids: number[]
}

export interface AgentPayload {
  name: string
  avatar_url: string
  description: string
  is_enabled: boolean
  config: AgentConfig
  tool_ids: number[]
  skill_ids: number[]
}

export interface ListParams {
  page?: number
  page_size?: number
  keyword?: string
  is_enabled?: boolean
  agent_id?: number
}

export interface SkillPayload {
  name: string
  description: string
  is_enabled: boolean
  content: string
  config: Record<string, unknown>
  agent_id?: number | null
}

export interface ToolPayload {
  name: string
  description: string
  is_enabled: boolean
  type: string
  config: Record<string, unknown>
  agent_id?: number | null
}

export interface ComponentPayload {
  name: string
  description: string
  is_enabled: boolean
  type: string
  config: Record<string, unknown>
  agent_id?: number | null
}

export interface PromptPayload {
  name: string
  description: string
  is_enabled: boolean
  content: string
  variables: string[]
  category: string
  agent_id?: number | null
}
