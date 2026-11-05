/** dev 静态版 mock：?wfMock=<scenario> 时注入 schema / 事件流 / 历史，供风格验收截图。 */

import type { WorkflowStreamEvent } from '../state/workflowReducer'
import { workflowReducer } from '../state/workflowReducer'
import { EMPTY_RUN_STATE, type RunHistoryItem, type WorkflowRunState, type WorkflowSchema } from '../types'

export type MockScenario = 'idle' | 'running' | 'success' | 'approval' | 'waiting' | 'error'

export const MOCK_SCENARIOS: MockScenario[] = ['idle', 'running', 'success', 'approval', 'waiting', 'error']

export function isMockScenario(value: string | null): value is MockScenario {
  return value !== null && (MOCK_SCENARIOS as string[]).includes(value)
}

export const mockSchema: WorkflowSchema = {
  application_id: '00000000-0000-4000-8000-000000000001',
  name: '市场调研工作流',
  description: '根据调研主题自动检索、分析并生成调研报告，重要结论需运营角色人工确认后发布。',
  flow_type: 'workflow',
  has_human_approval: true,
  inputs: [
    { name: 'query', type: 'string', required: true, description: '调研主题或问题', default_value: '' },
    { name: 'top_k', type: 'number', required: false, description: '检索结果条数', default_value: 5 },
    { name: 'detailed', type: 'boolean', required: false, description: '是否输出详细分析', default_value: false },
    { name: 'filters', type: 'object', required: false, description: '检索过滤条件', default_value: {} },
    { name: 'tags', type: 'array[string]', required: false, description: '标签列表', default_value: null },
    { name: 'scores', type: 'array[number]', required: false, description: '权重列表', default_value: null },
    { name: 'records', type: 'array[object]', required: false, description: '补充样本记录', default_value: null },
    { name: 'brief', type: 'file', required: false, description: '背景资料文件', default_value: null },
    { name: 'shots', type: 'image', required: false, description: '参考截图', default_value: null },
  ],
}

const approvalPayload = {
  type: 'human_approval',
  node_id: 'approve_publish',
  node_title: '确认发布调研报告',
  assignee_role: 'leader',
  instructions: '报告涉及对外发布，请运营负责人核对结论后批准。驳回将终止发布并保留草稿。',
  snapshot: {
    report_title: '2026 年智能座舱市场调研摘要',
    key_findings: ['渗透率同比 +18%', '价格带下移明显', '车机生态成为决策权重项'],
    word_count: 3560,
  },
}

function runningEvents(): WorkflowStreamEvent[] {
  return [
    { event: 'run_start', data: { run_id: 'mock-run-running', thread_id: 'mock-thread' } },
    { event: 'node_start', data: { node_id: 'start', node_type: 'start', title: '开始', inputs: { query: '2026 智能座舱市场' } } },
    { event: 'node_end', data: { node_id: 'start', status: 'success', outputs: { query: '2026 智能座舱市场' }, duration_ms: 12 } },
    { event: 'node_start', data: { node_id: 'search', node_type: 'knowledge', title: '知识库检索', inputs: { query: '2026 智能座舱市场', top_k: 5 } } },
    {
      event: 'node_end',
      data: {
        node_id: 'search',
        status: 'success',
        outputs: { hits: 5, top_score: 0.87 },
        duration_ms: 420,
      },
    },
    { event: 'node_start', data: { node_id: 'analyze', node_type: 'llm', title: '分析与撰写' } },
    { event: 'llm_token', data: { node_id: 'analyze', delta: '根据检索到的 5 份资料，' } },
    { event: 'llm_token', data: { node_id: 'analyze', delta: '智能座舱渗透率同比提升 18%，' } },
    { event: 'llm_token', data: { node_id: 'analyze', delta: '价格带整体下移……' } },
  ]
}

const successTail: WorkflowStreamEvent[] = [
  { event: 'node_end', data: { node_id: 'analyze', status: 'success', outputs: { draft: '调研报告草稿已生成' }, duration_ms: 5210 } },
  { event: 'node_start', data: { node_id: 'format', node_type: 'code', title: '格式化输出', inputs: { draft: '调研报告草稿已生成' } } },
  { event: 'node_end', data: { node_id: 'format', status: 'success', outputs: { final: true }, duration_ms: 30 } },
  {
    event: 'result',
    data: {
      output:
        '# 2026 年智能座舱市场调研摘要\n\n渗透率同比 +18%；价格带下移明显；车机生态成为购车决策权重项。建议优先布局中端价位生态合作。',
      run_id: 'mock-run-success',
      thread_id: 'mock-thread',
    },
  },
]

const errorTail: WorkflowStreamEvent[] = [
  { event: 'node_end', data: { node_id: 'analyze', status: 'error', error: 'LLM 调用超时（gateway 504）', duration_ms: 30000 } },
  { event: 'error', data: { message: '节点「分析与撰写」执行失败：LLM 调用超时，请稍后重试。', code: 'node_failed' } },
]

export function buildMockRunState(scenario: MockScenario): WorkflowRunState {
  if (scenario === 'idle') return EMPTY_RUN_STATE
  let state = EMPTY_RUN_STATE
  for (const evt of runningEvents()) state = workflowReducer(state, evt)
  if (scenario === 'running') return state
  if (scenario === 'success' || scenario === 'waiting' || scenario === 'approval') {
    for (const evt of successTail.slice(0, 1)) state = workflowReducer(state, evt)
  }
  if (scenario === 'success') {
    for (const evt of successTail.slice(1)) state = workflowReducer(state, evt)
    return state
  }
  if (scenario === 'approval' || scenario === 'waiting') {
    state = workflowReducer(state, {
      event: 'interrupted',
      data: { approval: approvalPayload, run_id: 'mock-run-int', thread_id: 'mock-thread' },
    })
    return state
  }
  for (const evt of errorTail) state = workflowReducer(state, evt)
  return state
}

/** running 场景下持续滴 token，模拟流式观感。 */
export const mockTokenDeltas = ['同时，车机生态的互联体验正在', '成为用户换机的关键动因之一。', '接下来将生成三档预算建议……']

export const mockRuns: RunHistoryItem[] = [
  {
    id: 'mock-run-success',
    thread_id: 'mock-thread',
    execute_status: 'success',
    input: { query: '2026 智能座舱市场' },
    output: { output: '# 2026 年智能座舱市场调研摘要…' },
    error_message: null,
    started_at: '2026-11-05T09:12:00Z',
    finished_at: '2026-11-05T09:12:26Z',
  },
  {
    id: 'mock-run-err',
    thread_id: 'mock-thread-2',
    execute_status: 'error',
    input: { query: '新能源 MPV 竞品对比' },
    output: null,
    error_message: '节点「分析与撰写」执行失败：LLM 调用超时',
    started_at: '2026-11-04T18:03:00Z',
    finished_at: '2026-11-04T18:04:12Z',
  },
]

export const mockApprovals: RunHistoryItem[] = [
  {
    id: 'mock-run-int',
    thread_id: 'mock-thread',
    execute_status: 'interrupted',
    input: { query: '2026 智能座舱市场' },
    output: null,
    error_message: null,
    started_at: '2026-11-05T10:02:00Z',
    finished_at: null,
    interrupt_payload: approvalPayload,
  },
]

/** mock 审批续跑事件：批准后走完剩余节点并出结果。 */
export const mockResumeEvents: WorkflowStreamEvent[] = [
  { event: 'run_start', data: { run_id: 'mock-run-resume', thread_id: 'mock-thread', resuming: true } },
  { event: 'node_start', data: { node_id: 'approve_publish', node_type: 'human_approval', title: '确认发布调研报告' } },
  { event: 'node_end', data: { node_id: 'approve_publish', status: 'success', outputs: { approved: true }, duration_ms: 4 } },
  { event: 'node_start', data: { node_id: 'publish', node_type: 'code', title: '发布报告' } },
  { event: 'node_end', data: { node_id: 'publish', status: 'success', outputs: { url: 'https://example.com/report/42' }, duration_ms: 60 } },
  {
    event: 'result',
    data: { output: '报告已发布：https://example.com/report/42', run_id: 'mock-run-resume', thread_id: 'mock-thread' },
  },
]
