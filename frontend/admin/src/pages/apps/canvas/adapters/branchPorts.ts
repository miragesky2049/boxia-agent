// 分支节点（if_else / intent）出口端口归一化。
// 动态端口以配置为准：if_else = 每个 case 一个口 + else，intent = 每个意图一个口 + "0"。
// 历史图里可能存在 coze/旧版本留下的 true/false、classificationId 等端口名，
// 加载时统一映射到当前动态端口，避免 FlowGram 为未知端口生成游离端点。

export const DEFAULT_IF_CASE_ID = 'case_1'
export const IF_ELSE_PORT = 'else'
export const INTENT_OTHER_PORT = '0'

interface RawCase {
  case_id?: unknown
  id?: unknown
  left?: unknown
  operator?: unknown
  right?: unknown
  expression?: unknown
  condition?: unknown
}

function toArray(raw: unknown): unknown[] {
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed
    } catch {
      // 非 JSON 串按空处理
    }
  }
  return []
}

/** 条件列表归一化：补齐 case_id，空列表时补一个默认「如果」，保证卡片/抽屉始终有如果分支。 */
export function normalizeIfElseCases(raw: unknown): RawCase[] {
  const cases = toArray(raw).filter((item): item is RawCase => !!item && typeof item === 'object')
  if (cases.length === 0) {
    return [{ case_id: DEFAULT_IF_CASE_ID, left: '', operator: 'eq', right: '' }]
  }
  return cases.map((item, idx) => ({
    ...item,
    case_id: String(item.case_id || item.id || `case_${idx + 1}`),
  }))
}

/** 条件列表的有效出口端口 ID（与 nodeRenderer 的动态端口保持一致）。 */
export function ifElsePortIds(raw: unknown): string[] {
  return normalizeIfElseCases(raw).map((item) => String(item.case_id))
}

/** 意图列表的有效出口端口 ID：与 parseIntentsValue 的 id 规则一致。 */
export function intentPortIds(raw: unknown): string[] {
  const ids: string[] = []
  toArray(raw).forEach((item, idx) => {
    if (typeof item === 'string') {
      if (item.trim()) ids.push(String(idx + 1))
      return
    }
    if (!item || typeof item !== 'object') return
    const record = item as Record<string, unknown>
    const name = String(record.name ?? record.intent ?? '').trim()
    if (!name) return
    const parsed = Number(record.id)
    ids.push(String(Number.isFinite(parsed) && parsed > 0 ? parsed : idx + 1))
  })
  return ids
}

/** 分支节点的默认出口端口：新增下游节点自动连线时使用首个有效分支口。 */
export function resolveFirstBranchOutputPort(
  typeKey: string,
  config: Record<string, unknown> | undefined,
): string | undefined {
  if (typeKey === 'if_else') {
    return ifElsePortIds(config?.cases)[0] ?? IF_ELSE_PORT
  }
  if (typeKey === 'intent') {
    return intentPortIds(config?.intents)[0] ?? INTENT_OTHER_PORT
  }
  return undefined
}

export interface BranchNodeSummary {
  id: string
  typeKey: string
  config?: Record<string, unknown>
}

/**
 * 把分支节点上的历史出口端口映射到当前动态端口。
 *
 * 映射规则（按边在 IR 中的顺序分配，避免同一端口被重复占用）：
 * - `false` → 优先 else，其次首个有效分支口
 * - `true` / 其他未知值 → 优先首个空闲有效分支口，其次 else / "0"
 * - 已是有效端口 → 原样保留
 */
export function normalizeBranchEdgePorts(
  nodes: BranchNodeSummary[],
  edges: Array<Record<string, unknown>>,
): void {
  const validPorts = new Map<string, string[]>()
  for (const node of nodes) {
    if (node.typeKey === 'if_else') {
      validPorts.set(node.id, [...ifElsePortIds(node.config?.cases), IF_ELSE_PORT])
    } else if (node.typeKey === 'intent') {
      validPorts.set(node.id, [...intentPortIds(node.config?.intents), INTENT_OTHER_PORT])
    }
  }
  if (validPorts.size === 0) return

  const usedPorts = new Map<string, Set<string>>()
  for (const edge of edges) {
    const sourceId = String(edge.sourceNodeID ?? '')
    const ports = validPorts.get(sourceId)
    if (!ports || ports.length === 0) continue

    let used = usedPorts.get(sourceId)
    if (!used) {
      used = new Set<string>()
      usedPorts.set(sourceId, used)
    }

    const current = String(edge.sourcePortID ?? '')
    if (ports.includes(current)) {
      used.add(current)
      continue
    }

    const fallbackPort = ports[ports.length - 1]!
    const preferred =
      current === 'false'
        ? [fallbackPort, ...ports.filter((port) => port !== fallbackPort)]
        : [...ports.filter((port) => port !== fallbackPort), fallbackPort]
    const target = preferred.find((port) => !used.has(port)) ?? preferred[0]!
    edge.sourcePortID = target
    used.add(target)
  }
}
