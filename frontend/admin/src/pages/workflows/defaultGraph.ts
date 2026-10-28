import type { WorkflowGraph } from '../../api/workflows'

/** 预置最小骨架：Start → LLM → End，租户打开画布就能跑通。 */
export function buildDefaultSkeletonGraph(): WorkflowGraph {
  return {
    variables: [{ key: 'query', type: 'string', required: true, default: '' }],
    nodes: [
      {
        id: 'start_1',
        type: 'start',
        position: { x: 0, y: 0 },
        data: { output_schema: { query: 'string' } },
      },
      {
        id: 'llm_1',
        type: 'llm',
        position: { x: 320, y: 0 },
        data: {
          model_id: 'default',
          system_prompt_tpl: '',
          user_prompt_tpl: '{{query}}',
          temperature: 0.7,
        },
      },
      {
        id: 'end_1',
        type: 'end',
        position: { x: 640, y: 0 },
        data: { output_tpl: { answer: '{{llm_1.output}}' } },
      },
    ],
    edges: [
      { source: 'start_1', target: 'llm_1' },
      { source: 'llm_1', target: 'end_1' },
    ],
  }
}
