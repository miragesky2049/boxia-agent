import { request } from './client'
import type {
  ComponentPayload,
  ComponentResource,
  ListParams,
  PageResult,
  PromptPayload,
  PromptResource,
  Skill,
  SkillPayload,
  Tool,
  ToolPayload,
} from './types'

export interface ClonePayload {
  agent_id: number
  name?: string | null
}

export interface ResourceApi<TOut, TPayload> {
  list: (params: ListParams) => Promise<PageResult<TOut>>
  create: (payload: TPayload) => Promise<TOut>
  update: (id: number, payload: TPayload) => Promise<TOut>
  remove: (id: number) => Promise<void>
  clone: (id: number, payload: ClonePayload) => Promise<TOut>
}

function createResourceApi<TOut, TPayload>(base: string): ResourceApi<TOut, TPayload> {
  return {
    async list(params) {
      const query = new URLSearchParams()
      query.set('page', String(params.page ?? 1))
      query.set('page_size', String(params.page_size ?? 20))
      if (params.keyword) query.set('keyword', params.keyword)
      if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled))
      if (params.agent_id !== undefined) query.set('agent_id', String(params.agent_id))
      return request<PageResult<TOut>>(`${base}?${query.toString()}`)
    },
    async create(payload) {
      return request<TOut>(base, { method: 'POST', body: JSON.stringify(payload) })
    },
    async update(id, payload) {
      return request<TOut>(`${base}/${id}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
      })
    },
    async remove(id) {
      await request<void>(`${base}/${id}`, { method: 'DELETE' })
    },
    async clone(id, payload) {
      return request<TOut>(`${base}/${id}/clone`, {
        method: 'POST',
        body: JSON.stringify({ agent_id: payload.agent_id, name: payload.name ?? null }),
      })
    },
  }
}

export const skillsApi = createResourceApi<Skill, SkillPayload>('/admin/skills')
export const toolsApi = createResourceApi<Tool, ToolPayload>('/admin/tools')
export const componentsApi = createResourceApi<ComponentResource, ComponentPayload>(
  '/admin/components',
)
export const promptsApi = createResourceApi<PromptResource, PromptPayload>('/admin/prompts')
