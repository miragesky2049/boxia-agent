import { request } from './client'

// 0074 PRD F6：管理端 MCP server 发现接口。
// discover 结果仅供人工勾选，勾选快照写入画布 config.mcpServers 后运行时不再 discover。

export interface McpToolSnapshot {
  name: string
  description?: string
  // JSON Schema 快照：admin 侧只整体透传回写（discover 勾选 → 画布 config），不读其结构；
  // 声明为 object 根而非 Record<string, unknown>，兼容 antd 表单 store 的递归 Partial 推断
  inputSchema?: object
}

export interface McpDiscoverResult {
  serverUrl: string
  tools: McpToolSnapshot[]
  fromCache: boolean
}

export function discoverMcpTools(
  serverUrl: string,
  headers?: Record<string, string>,
): Promise<McpDiscoverResult> {
  return request<McpDiscoverResult>('/admin/mcp-servers/discover', {
    method: 'POST',
    body: JSON.stringify({ serverUrl, headers }),
  })
}
