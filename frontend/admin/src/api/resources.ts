import { request } from './client'
import type { ListParams, PageResult, Tool, ToolPayload } from './types'

export interface ToolTestInvokeResult {
  success: boolean
  duration_ms: number
  output: string
  error: string
}

function buildQuery(params: ListParams): string {
  const query = new URLSearchParams()
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.page_size ?? 20))
  if (params.keyword) query.set('keyword', params.keyword)
  if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled))
  return query.toString()
}

export const toolsApi = {
  async list(params: ListParams): Promise<PageResult<Tool>> {
    return request<PageResult<Tool>>(`/admin/tools?${buildQuery(params)}`)
  },
  async create(payload: ToolPayload): Promise<Tool> {
    return request<Tool>('/admin/tools', { method: 'POST', body: JSON.stringify(payload) })
  },
  async update(id: string, payload: ToolPayload): Promise<Tool> {
    return request<Tool>(`/admin/tools/${id}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    })
  },
  async remove(id: string): Promise<void> {
    await request<void>(`/admin/tools/${id}`, { method: 'DELETE' })
  },
}

export async function testInvokeTool(
  id: string,
  args: Record<string, unknown>,
): Promise<ToolTestInvokeResult> {
  return request<ToolTestInvokeResult>(`/admin/tools/${id}/test-invoke`, {
    method: 'POST',
    body: JSON.stringify({ arguments: args }),
  })
}

// ---------- MCP 自动同步 ----------

export interface McpPulledTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
}

export interface McpPullResult {
  server_url: string
  tools: McpPulledTool[]
}

export async function pullMcpTools(serverUrl: string): Promise<McpPullResult> {
  return request<McpPullResult>('/admin/tools/pull-mcp-tools', {
    method: 'POST',
    body: JSON.stringify({ server_url: serverUrl }),
  })
}

export interface McpImportItem {
  name: string
  description: string
  tool_name_remote: string
  input_schema: Record<string, unknown>
}

export async function importMcpTools(
  serverUrl: string,
  items: McpImportItem[],
): Promise<{ created: Tool[] }> {
  return request<{ created: Tool[] }>('/admin/tools/import-mcp-tools', {
    method: 'POST',
    body: JSON.stringify({ server_url: serverUrl, tools: items }),
  })
}

// ---------- curl 解析 ----------

export interface ParseCurlResult {
  method: string
  url: string
  headers: Record<string, string>
  body: Record<string, unknown> | null
  notes: string[]
}

export async function parseCurl(curlCommand: string): Promise<ParseCurlResult> {
  return request<ParseCurlResult>('/admin/tools/parse-curl', {
    method: 'POST',
    body: JSON.stringify({ curl_command: curlCommand }),
  })
}

// ---------- 知识库文档（用于 LLM 节点 RAG 配置） ----------

export interface DocumentOption {
  id: string
  title: string
  ingest_status: string
  is_enabled: boolean
}

export async function listDocumentsForRetrieval(
  pageSize = 200,
): Promise<DocumentOption[]> {
  const query = new URLSearchParams()
  query.set('page', '1')
  query.set('page_size', String(pageSize))
  query.set('is_enabled', 'true')
  const result = await request<PageResult<DocumentOption>>(`/admin/documents?${query.toString()}`)
  return result.items
}
