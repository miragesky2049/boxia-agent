import { request } from './client'

export interface ToolCallTrace {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  observation: string
  is_error: boolean
}

export interface AgentRunResponse {
  agent_id: string
  run_id: string
  conversation_id: string
  content: string
  tool_traces: ToolCallTrace[]
  iterations: number
  usage: Record<string, number>
  finish_reason: string
}

export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}

export async function runAgent(
  agentId: string,
  body: { query: string; conversation_id?: string; history?: ChatHistoryItem[] },
): Promise<AgentRunResponse> {
  return request<AgentRunResponse>(`/user/agents/${agentId}/run`, {
    method: 'POST',
    body: JSON.stringify({
      query: body.query,
      conversation_id: body.conversation_id ?? '',
      history: body.history ?? [],
    }),
  })
}

/** SSE 事件类型：与后端 web/deps/sse.py 对齐 */
export type AgentStreamEvent =
  | { event: 'run_start'; data: { run_id: string; tools: string[] } }
  | { event: 'llm_start'; data: { iteration: number; messages: number; tools: number } }
  | {
      event: 'llm_end'
      data: {
        iteration: number
        content: string
        tool_calls: Array<{ id: string; name: string; arguments: string }>
        usage: Record<string, number>
        /** 增量 token 是否已通过 llm_token 推送 */
        usage_streamed?: boolean
      }
    }
  | { event: 'llm_token'; data: { delta: string } }
  | {
      event: 'tool_start'
      data: { tool_call_id: string; name: string; arguments: Record<string, unknown> }
    }
  | {
      event: 'tool_end'
      data: { tool_call_id: string; name: string; observation: string; is_error: boolean }
    }
  | { event: 'final'; data: Record<string, unknown> }
  | { event: 'result'; data: AgentRunResponse }
  | { event: 'error'; data: { message: string; code: number } }

/** 对话流 SSE 事件：中间消息与问答中断由流程节点驱动。 */
export type ChatflowStreamEvent =
  | {
      event: 'run_start'
      data: { conversation_id: string; thread_id: string; run_id: string }
    }
  | { event: 'node_start'; data: { node_id: string; node_type?: string; inputs?: unknown } }
  | {
      event: 'node_end'
      data: {
        node_id: string
        status?: string
        outputs?: unknown
        duration_ms?: number
        error?: string
      }
    }
  | { event: 'output_message'; data: { content: string; role?: string; stream?: boolean } }
  | {
      event: 'question'
      data: {
        node_id: string
        question: string
        options: string[]
        conversation_id: string
        thread_id: string
        run_id: string
      }
    }
  | {
      event: 'interrupted'
      data: {
        approval: Record<string, unknown>
        conversation_id?: string
        thread_id?: string
        run_id?: string
      }
    }
  | { event: 'result'; data: { outputs?: Record<string, unknown> } }
  | { event: 'error'; data: { message: string; code?: string | number } }
  | { event: 'final'; data: Record<string, unknown> }

export interface ChatflowRunBody {
  message?: string
  conversation_id?: string
  thread_id?: string
  inputs?: Record<string, unknown>
  resume?: Record<string, unknown>
}

interface StreamOptions {
  signal?: AbortSignal
}

/** 以 SSE 方式发起 POST：EventSource 不支持 POST，这里用 fetch + ReadableStream 解析。 */
export async function postSseStream<TEvent>(
  url: string,
  body: unknown,
  onEvent: (evt: TEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = (await import('../auth/tokenStore')).getAccessToken()
  const tenantCode = (await import('../tenant/scope')).getTenantCode()

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (token) headers.Authorization = `Bearer ${token}`
  if (tenantCode) headers['X-Tenant-Code'] = tenantCode

  const response = await fetch(`${baseUrl}${url}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal: options.signal,
  })

  if (!response.ok || !response.body) {
    let message = `流式调用失败（HTTP ${response.status}）`
    try {
      const data = (await response.json()) as { detail?: string }
      if (data?.detail) message = data.detail
    } catch {
      // ignore
    }
    throw new Error(message)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  // SSE 帧以 \n\n 分隔；每帧可能包含 event: 和 data: 行
  const handleFrame = (frame: string) => {
    if (!frame.trim()) return
    let eventName = 'message'
    let dataLine = ''
    for (const rawLine of frame.split('\n')) {
      const line = rawLine.replace(/\r$/, '')
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLine = line.slice(5).trim()
      }
    }
    if (!dataLine) return
    try {
      const data = JSON.parse(dataLine) as Record<string, unknown>
      onEvent({ event: eventName, data } as TEvent)
    } catch {
      // 忽略解析失败的帧
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      handleFrame(frame)
    }
  }
  if (buffer.trim()) handleFrame(buffer)
}

/**
 * 以 SSE 方式运行 agent。调用方通过 onEvent 消费每个事件；
 * 拿到 result 事件后可终止循环。
 */
export async function runAgentStream(
  agentId: string,
  body: { query: string; conversation_id?: string; history?: ChatHistoryItem[] },
  onEvent: (evt: AgentStreamEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  return postSseStream<AgentStreamEvent>(
    `/user/agents/${agentId}/run/stream`,
    {
      query: body.query,
      conversation_id: body.conversation_id ?? '',
      history: body.history ?? [],
    },
    onEvent,
    options,
  )
}

/** 以 SSE 方式运行对话流；message 与 resume 二选一。 */
export async function runChatflowStream(
  agentId: string,
  body: ChatflowRunBody,
  onEvent: (evt: ChatflowStreamEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  return postSseStream<ChatflowStreamEvent>(
    `/user/agents/${agentId}/chatflow/run/stream`,
    {
      message: body.message ?? '',
      conversation_id: body.conversation_id || undefined,
      thread_id: body.thread_id || undefined,
      inputs: body.inputs ?? {},
      resume: body.resume ?? undefined,
    },
    onEvent,
    options,
  )
}
