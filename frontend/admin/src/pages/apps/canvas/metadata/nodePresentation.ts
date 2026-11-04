import type { ConfigFieldMeta, NodeMeta } from '../../../../api/nodeMeta';

// 后端 node_meta.py 是展示事实源；本文件只做「接口结果 → 前端展示结构」的一层适配。
// 本地 fallback（ICON_MAP / NEXT_FALLBACK / SECTION_DEFS）仅在后端字段缺失时兜底。

export interface NextRecommendation {
  typeKey: string;
  label: string;
}

export interface ConfigSectionShape {
  title: string;
  fields: ConfigFieldMeta[];
}

export interface CategoryGroup {
  key: string;
  label: string;
  items: NodeMeta[];
}

// 与 coze「添加节点」面板分组保持一致；basic/control 是本地补充的节点分组
export const CATEGORY_ORDER = [
  'basic', 'ai', 'plugin', 'workflow', 'logic', 'io', 'control',
  'knowledge', 'component', 'conversation', 'history', 'message',
  'database', 'memory', 'image', 'media', 'misc',
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  basic: '基础节点',
  ai: '大模型',
  plugin: '插件',
  workflow: '工作流',
  logic: '业务逻辑',
  io: '输入&输出',
  control: '流程控制',
  knowledge: '知识库&数据',
  component: '组件',
  conversation: '会话管理',
  history: '会话历史',
  message: '消息',
  database: '数据库（未启用）',
  memory: '长期记忆（未启用）',
  image: '图像处理（未启用）',
  media: '音视频处理（未启用）',
  misc: '其他',
};

export function resolveIcon(meta: NodeMeta | undefined): string {
  return meta?.icon || '';
}

export function resolveSubtitleHint(meta: NodeMeta | undefined): string {
  return meta?.subtitle_hint || '';
}

// 添加节点面板分组：按 CATEGORY_ORDER 排序，后端出现的未知分类追加在末尾
export function buildCategoryGroups(
  metas: NodeMeta[],
  filter?: (meta: NodeMeta) => boolean,
): CategoryGroup[] {
  const visible = filter ? metas.filter(filter) : metas;
  const extraKeys = Array.from(new Set(visible.map((m) => m.category)))
    .filter((key) => !(CATEGORY_ORDER as readonly string[]).includes(key));
  const keys = [...CATEGORY_ORDER, ...extraKeys];
  return keys
    .map((key) => ({
      key,
      label: CATEGORY_LABELS[key] || key,
      items: visible.filter((m) => m.category === key),
    }))
    .filter((group) => group.items.length > 0);
}

// 配置字段分组：优先读后端 field.group；全部为空时返回 null，由本地 SECTION_DEFS 兜底
export function groupFieldsByMetaGroup(fields: ConfigFieldMeta[]): ConfigSectionShape[] | null {
  if (!fields.some((f) => f.group)) return null;
  const order: string[] = [];
  const grouped = new Map<string, ConfigFieldMeta[]>();
  for (const f of fields) {
    const key = f.group || '其他';
    if (!grouped.has(key)) {
      grouped.set(key, []);
      order.push(key);
    }
    grouped.get(key)!.push(f);
  }
  return order.map((title) => ({ title, fields: grouped.get(title)! }));
}

// 「下一步」推荐兜底：仅当后端 meta 缺失 next_recommendations 时使用
const NEXT_FALLBACK: Record<string, string[]> = {
  start: ['llm', 'dataset', 'if_else', 'code'],
  llm: ['if_else', 'dataset', 'http', 'end'],
  http: ['code', 'if_else', 'end'],
  if_else: ['llm', 'code', 'end'],
  code: ['if_else', 'llm', 'end'],
  dataset: ['llm', 'if_else'],
  agent_loop: ['if_else', 'end'],
  api_plugin: ['code', 'if_else', 'end'],
  text_processor: ['llm', 'if_else', 'end'],
  json_stringify: ['code', 'llm', 'end'],
  json_parser: ['code', 'llm', 'end'],
  set_variable: ['llm', 'if_else', 'end'],
  variable_merge: ['llm', 'end'],
  human_approval: ['llm', 'end'],
  subworkflow: ['llm', 'if_else', 'end'],
  loop: ['llm', 'if_else', 'end'],
  batch: ['llm', 'end'],
  dataset_write: ['llm', 'end'],
  create_conversation: ['create_message', 'end'],
};

export function resolveNextRecommendations(
  meta: NodeMeta | undefined,
  keyToMeta: Record<string, NodeMeta>,
  typeKey?: string,
): NextRecommendation[] {
  const resolvedKey = meta?.type_key || typeKey || '';
  const keys = meta?.next_recommendations?.length
    ? meta.next_recommendations
    : NEXT_FALLBACK[resolvedKey] || [];
  return keys.map((key) => ({
    typeKey: key,
    label: keyToMeta[key]?.title || key,
  }));
}
