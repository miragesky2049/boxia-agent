import { request } from './client'

export interface AgentMemoryItem {
  memory_id: string
  kind: 'preference' | 'fact' | 'episode' | string
  content: string
  updated_at: string | null
  hit_count: number
}

export interface MemoryListResult {
  items: AgentMemoryItem[]
  total: number
}

export async function listMemories(applicationId: string): Promise<MemoryListResult> {
  return request<MemoryListResult>(
    `/user/memories?application_id=${encodeURIComponent(applicationId)}`,
  )
}

export async function deleteMemory(applicationId: string, memoryId: string): Promise<void> {
  await request<{ deleted: number }>(
    `/user/memories/${memoryId}?application_id=${encodeURIComponent(applicationId)}`,
    { method: 'DELETE' },
  )
}

export async function clearMemories(applicationId: string): Promise<number> {
  const result = await request<{ deleted: number }>(
    `/user/memories?application_id=${encodeURIComponent(applicationId)}&confirm=true`,
    { method: 'DELETE' },
  )
  return result.deleted
}
