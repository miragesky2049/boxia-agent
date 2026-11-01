import type { NodeMeta } from '../../../api/nodeMeta';
import {
  resolveNextRecommendations,
  type NextRecommendation,
} from '../canvas/metadata/nodePresentation';

export type { NextRecommendation };

// 推荐下游节点：优先读后端 meta.next_recommendations，缺失时走本地 fallback
export function getNextRecommendations(
  typeKey: string,
  keyToMeta: Record<string, NodeMeta> = {},
): NextRecommendation[] {
  return resolveNextRecommendations(keyToMeta[typeKey], keyToMeta, typeKey);
}
