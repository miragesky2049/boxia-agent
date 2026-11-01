// 图标映射的 key 必须与后端 node_meta.py 的 type_key 完全一致，
// 否则节点会退化成默认圆点图标。
const ICON_MAP: Record<string, { emoji: string; fallbackColor: string }> = {
  // 控制流
  start: { emoji: '▶', fallbackColor: '#3b82f6' },
  end: { emoji: '■', fallbackColor: '#ef4444' },
  if_else: { emoji: 'IF', fallbackColor: '#ec4899' },
  loop: { emoji: '↻', fallbackColor: '#eab308' },
  batch: { emoji: '≡', fallbackColor: '#eab308' },
  break: { emoji: '‖', fallbackColor: '#64748b' },
  continue: { emoji: '→', fallbackColor: '#64748b' },
  human_approval: { emoji: '👤', fallbackColor: '#f97316' },
  subworkflow: { emoji: '▣', fallbackColor: '#64748b' },
  comment: { emoji: '✎', fallbackColor: '#eab308' },

  // AI / 逻辑
  llm: { emoji: 'AI', fallbackColor: '#8b5cf6' },
  agent_loop: { emoji: '◉', fallbackColor: '#8b5cf6' },
  http: { emoji: '🌐', fallbackColor: '#f59e0b' },
  api_plugin: { emoji: '⌗', fallbackColor: '#f59e0b' },
  code: { emoji: '{;}', fallbackColor: '#10b981' },

  // 数据
  dataset: { emoji: 'DB', fallbackColor: '#6366f1' },
  dataset_write: { emoji: '✎', fallbackColor: '#6366f1' },
  text_processor: { emoji: '¶', fallbackColor: '#ec4899' },
  json_stringify: { emoji: '{}', fallbackColor: '#64748b' },
  json_parser: { emoji: '{ }', fallbackColor: '#64748b' },

  // 变量
  set_variable: { emoji: 'ƒ', fallbackColor: '#a855f7' },
  variable_merge: { emoji: '⋈', fallbackColor: '#a855f7' },

  // 会话 / 消息
  create_conversation: { emoji: '＋', fallbackColor: '#10b981' },
  update_conversation: { emoji: '✎', fallbackColor: '#10b981' },
  delete_conversation: { emoji: '✕', fallbackColor: '#10b981' },
  query_conversation_list: { emoji: '☰', fallbackColor: '#10b981' },
  query_conversation_history: { emoji: '☷', fallbackColor: '#10b981' },
  create_message: { emoji: '↑', fallbackColor: '#10b981' },
  update_message: { emoji: '✎', fallbackColor: '#10b981' },
  delete_message: { emoji: '✕', fallbackColor: '#10b981' },
  clear_context: { emoji: '⌫', fallbackColor: '#10b981' },
};

function hexToRgba(hex: string, alpha: number): string {
  const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!m) return `rgba(99,102,241,${alpha})`;
  const r = parseInt(m[1], 16);
  const g = parseInt(m[2], 16);
  const b = parseInt(m[3], 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

export function NodeIcon({ typeKey, color, size = 24 }: { typeKey: string; color: string; size?: number }) {
  const icon = ICON_MAP[typeKey] || { emoji: '•', fallbackColor: color || '#6366f1' };
  const bgColor = hexToRgba(color || icon.fallbackColor, 0.12);
  const fgColor = color || icon.fallbackColor;
  const fontSize = icon.emoji.length <= 2 ? 11 : 9;
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: 6,
        background: bgColor,
        color: fgColor,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize,
        fontWeight: 700,
        flexShrink: 0,
        lineHeight: 1,
      }}
    >
      {icon.emoji}
    </div>
  );
}
