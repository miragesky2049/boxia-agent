import { request } from './client'

export interface DatasetItem {
  id: string
  title: string
}

// 复用 /admin/documents 作为知识库列表（后端暂无独立 datasets 表）
export async function listDatasets(): Promise<DatasetItem[]> {
  const res = await request<{ items: Array<{ id: string; title: string }> }>(
    '/admin/documents?page=1&page_size=100'
  )
  return (res.items || []).map((d) => ({ id: d.id, title: d.title }))
}
