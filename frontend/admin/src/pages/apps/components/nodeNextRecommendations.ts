// V10：节点类型 → 推荐下游节点映射（前端硬编码，对齐 Dify "下一步" 交互）
export interface NextRecommendation {
  typeKey: string;
  label: string;
}

// 按当前节点 type_key 查推荐下游；未列出的类型不显示推荐区块
const NEXT_MAP: Record<string, NextRecommendation[]> = {
  start: [
    { typeKey: 'llm', label: '大语言模型' },
    { typeKey: 'dataset', label: '知识检索' },
    { typeKey: 'if_else', label: '条件分支' },
    { typeKey: 'code', label: '代码' },
  ],
  llm: [
    { typeKey: 'if_else', label: '条件分支' },
    { typeKey: 'dataset', label: '知识检索' },
    { typeKey: 'http', label: 'HTTP 请求' },
    { typeKey: 'end', label: '结束' },
  ],
  http: [
    { typeKey: 'code', label: '代码' },
    { typeKey: 'if_else', label: '条件分支' },
    { typeKey: 'end', label: '结束' },
  ],
  if_else: [
    { typeKey: 'llm', label: '大语言模型' },
    { typeKey: 'code', label: '代码' },
    { typeKey: 'end', label: '结束' },
  ],
  code: [
    { typeKey: 'if_else', label: '条件分支' },
    { typeKey: 'llm', label: '大语言模型' },
    { typeKey: 'end', label: '结束' },
  ],
  dataset: [
    { typeKey: 'llm', label: '大语言模型' },
    { typeKey: 'if_else', label: '条件分支' },
  ],
};

export function getNextRecommendations(typeKey: string): NextRecommendation[] {
  return NEXT_MAP[typeKey] || [];
}
