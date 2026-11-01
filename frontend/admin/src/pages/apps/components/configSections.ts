import type { ConfigFieldMeta } from '../../../api/nodeMeta';

// 节点配置分组：按 node type_key 把 config_fields 分成若干 section
// 字段名与后端 node_meta.py 保持一致（camelCase）
export interface ConfigSection {
  title: string;
  fields: ConfigFieldMeta[];
}

const SECTION_DEFS: Record<string, Array<{ title: string; match: (f: ConfigFieldMeta) => boolean }>> = {
  start: [
    { title: '启动参数', match: (f) => f.name === 'inputs' },
  ],
  end: [
    { title: '输出设置', match: (f) => f.name === 'content' },
  ],
  comment: [
    { title: '便签内容', match: (f) => f.name === 'content' },
  ],
  api_plugin: [
    { title: '插件设置', match: (f) => ['pluginName', 'description'].includes(f.name) },
  ],
  text_processor: [
    { title: '文本处理设置', match: (f) => ['operation', 'find', 'replaceWith'].includes(f.name) },
  ],
  set_variable: [
    { title: '变量设置', match: (f) => ['variableName', 'value'].includes(f.name) },
  ],
  human_approval: [
    { title: '审批设置', match: (f) => ['assignee_role', 'instructions'].includes(f.name) },
  ],
  create_conversation: [
    { title: '会话设置', match: (f) => ['title', 'app_id'].includes(f.name) },
  ],
  update_conversation: [
    { title: '会话设置', match: (f) => ['title'].includes(f.name) },
  ],
  query_conversation_list: [
    { title: '查询设置', match: (f) => ['app_id', 'limit'].includes(f.name) },
  ],
  query_conversation_history: [
    { title: '查询设置', match: (f) => ['limit'].includes(f.name) },
  ],
  create_message: [
    { title: '消息设置', match: (f) => ['role', 'content'].includes(f.name) },
  ],
  update_message: [
    { title: '消息设置', match: (f) => ['content'].includes(f.name) },
  ],
  llm: [
    { title: '模型设置', match: (f) => ['modleName', 'temperature', 'maxTokens'].includes(f.name) },
    { title: '技能', match: (f) => f.name === 'tools' },
    { title: '输入变量', match: (f) => f.name === 'inputs' },
    { title: '视觉理解', match: (f) => f.name === 'images' },
    { title: '提示词', match: (f) => ['prompt', 'systemPrompt'].includes(f.name) },
    { title: '高级', match: (f) => ['needHistory', 'historyLimit'].includes(f.name) },
  ],
  http: [
    { title: '请求设置', match: (f) => ['url', 'method', 'pathParams', 'queryParams', 'headers', 'bodyType', 'bodyJson', 'bodyForm'].includes(f.name) },
    { title: '认证', match: (f) => ['authType', 'authToken', 'authSecret'].includes(f.name) },
    { title: '高级', match: (f) => ['timeoutMs'].includes(f.name) },
  ],
  if_else: [
    { title: '条件分支', match: (f) => f.name === 'cases' },
  ],
  code: [
    { title: '输入变量', match: (f) => f.name === 'inputs' },
    { title: '代码', match: (f) => ['code', 'timeoutMs'].includes(f.name) },
  ],
  dataset: [
    { title: '知识库设置', match: (f) => ['datasetId', 'topK', 'scoreThreshold'].includes(f.name) },
  ],
  dataset_write: [
    { title: '知识库设置', match: (f) => ['datasetId'].includes(f.name) },
  ],
  loop: [
    { title: '循环设置', match: (f) => ['loopType', 'loopCount', 'parallel'].includes(f.name) },
  ],
  subworkflow: [
    { title: '调用设置', match: (f) => ['workflowId'].includes(f.name) },
  ],
  batch: [
    { title: '批处理设置', match: (f) => ['parallelCount'].includes(f.name) },
  ],
  agent_loop: [
    { title: '模型设置', match: (f) => ['modleName', 'tools'].includes(f.name) },
    { title: '提示词', match: (f) => ['systemPrompt', 'plannerPrompt', 'reflectorPrompt'].includes(f.name) },
    { title: '高级', match: (f) => ['maxToolRounds', 'maxReflectRounds'].includes(f.name) },
  ],
};

export function groupConfigFields(typeKey: string, fields: ConfigFieldMeta[]): ConfigSection[] {
  const defs = SECTION_DEFS[typeKey];
  if (!defs) {
    return [{ title: '配置', fields }];
  }
  const sections: ConfigSection[] = defs.map((d) => ({ title: d.title, fields: [] }));
  const rest: ConfigFieldMeta[] = [];
  for (const f of fields) {
    const idx = defs.findIndex((d) => d.match(f));
    if (idx >= 0) sections[idx].fields.push(f);
    else rest.push(f);
  }
  const nonEmpty = sections.filter((s) => s.fields.length > 0);
  if (rest.length > 0) nonEmpty.push({ title: '其他', fields: rest });
  return nonEmpty.length > 0 ? nonEmpty : [{ title: '配置', fields }];
}
