/** 用户端接口数据类型，与后端 web/user/schemas 保持一致。 */

export interface User {
  id: string
  username: string
  display_name: string
  tenant_id: string
  role_id: string
}

export interface UserProfile extends User {
  role_code: string
  role_name: string
  permissions: string[]
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string
  refresh_expires_in: number
  user: User
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface UserAgentSummary {
  id: string
  name: string
  avatar_url: string
  description: string
  is_enabled: boolean
}

export interface UserSkill {
  id: string
  name: string
  description: string
  content: string
  config: Record<string, unknown>
  is_enabled: boolean
}

export interface UserTool {
  id: string
  name: string
  description: string
  type: string
  config: Record<string, unknown>
  is_enabled: boolean
}

export type UserComponent = UserTool

export interface UserPrompt {
  id: string
  name: string
  description: string
  content: string
  variables: string[]
  category: string
  is_enabled: boolean
}

export interface UserAgentDetail extends UserAgentSummary {
  config: Record<string, unknown>
  skills: UserSkill[]
  tools: UserTool[]
  components: UserComponent[]
  prompts: UserPrompt[]
}
