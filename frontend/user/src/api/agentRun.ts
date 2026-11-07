export interface ToolCallTrace {
  tool_call_id: string
  // 0074 PRD F10 实机验收修正：后端 result.tool_traces 条目实际字段为 name（与 tool_end 帧一致）
  name: string
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

/** 知识库引用来源（后端 agent_loop chunks_meta 口径，excerpt 已截断） */
export interface ToolChunkRef {
  dataset_id?: string
  dataset_name: string
  chunk_id: string
  score?: number
  excerpt?: string
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
      data: {
        tool_call_id: string
        name: string
        observation: string
        is_error: boolean
        /** 0074 PRD F5.3：知识库命中来源（additive，仅检索工具携带） */
        chunks?: ToolChunkRef[]
      }
    }
  /** 0074 PRD F10：敏感工具待审批挂起（快照仅后端留存，帧内只有展示字段） */
  | {
      event: 'interrupted'
      data: {
        approval: {
          type: string
          node_id?: string
          iteration?: number
          tool_round?: number
          pending_tool_calls?: Array<{ id: string; name: string; arguments: string }>
          awaiting_calls?: Array<{ id: string; name: string; arguments: string }>
        }
        conversation_id: string
        thread_id: string
        run_id: string
      }
    }
  /** 0074 PRD F4：深度模式 plan/reflect 阶段结果（additive，快速反应模式无此帧） */
  | {
      event: 'plan'
      data: { content: string; tasks: Array<{ id?: string; goal?: string; acceptance?: string }> }
    }
  | {
      event: 'reflect'
      data: {
        content: string
        reflect_round: number
        done?: boolean
        critique?: string
        suggestion?: string
      }
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

/** 统一对话入口请求体（0074 PRD M3 端点收敛：chatflow 与 agent 共用一个端点）。 */
export interface ConversationRunBody {
  message?: string
  conversation_id?: string
  thread_id?: string
  /** F8：agent 型省略 history 以启用服务端记忆（undefined 与 [] 语义不同） */
  history?: ChatHistoryItem[]
  /** F9：随消息携带的图片 URL（后端 visionEnabled 门控） */
  images?: string[]
  /** F10：审批裁决 {approved, comment} */
  resume?: Record<string, unknown>
  /** 对话流启动变量（agent 通道忽略） */
  inputs?: Record<string, unknown>
}

/**
 * 以 SSE 方式运行智能体对话（统一入口，服务端按 flow_type 分派）。
 * 调用方通过 onEvent 消费每个事件；拿到 result/interrupted 事件后可终止循环。
 */
export async function runAgentStream(
  agentId: string,
  body: ConversationRunBody,
  onEvent: (evt: AgentStreamEvent) => void,
  options: StreamOptions = {},
): Promise<void> {
  return postSseStream<AgentStreamEvent>(
    `/user/agents/${agentId}/chatflow/run/stream`,
    {
      message: body.message ?? '',
      conversation_id: body.conversation_id || undefined,
      thread_id: body.thread_id || undefined,
      history: body.history,
      images: body.images ?? [],
      resume: body.resume,
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
