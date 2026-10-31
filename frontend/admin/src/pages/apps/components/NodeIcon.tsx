const ICON_MAP: Record<string, { emoji: string; fallbackColor: string }> = {
  start: { emoji: '▶', fallbackColor: '#3b82f6' },
  end: { emoji: '■', fallbackColor: '#ef4444' },
  llm: { emoji: 'AI', fallbackColor: '#8b5cf6' },
  http: { emoji: '🌐', fallbackColor: '#f59e0b' },
  if_else: { emoji: 'IF', fallbackColor: '#ec4899' },
  code: { emoji: '{;}', fallbackColor: '#10b981' },
  dataset: { emoji: 'DB', fallbackColor: '#6366f1' },
  dataset_write: { emoji: '✎', fallbackColor: '#6366f1' },
  loop: { emoji: '↻', fallbackColor: '#eab308' },
  batch: { emoji: '≡', fallbackColor: '#eab308' },
  subworkflow: { emoji: '▣', fallbackColor: '#64748b' },
  variable_set: { emoji: 'ƒ', fallbackColor: '#a855f7' },
  variable_merge: { emoji: '⋈', fallbackColor: '#a855f7' },
  text_processor: { emoji: '¶', fallbackColor: '#ec4899' },
  json_tools: { emoji: '{}', fallbackColor: '#64748b' },
  conversation_create: { emoji: '✉', fallbackColor: '#10b981' },
  conversation_update: { emoji: '✎', fallbackColor: '#10b981' },
  conversation_list: { emoji: '☰', fallbackColor: '#10b981' },
  conversation_history: { emoji: '☰', fallbackColor: '#10b981' },
  message_create: { emoji: '↑', fallbackColor: '#10b981' },
  message_update: { emoji: '✎', fallbackColor: '#10b981' },
  message_list: { emoji: '☰', fallbackColor: '#10b981' },
  message_delete: { emoji: '✕', fallbackColor: '#10b981' },
  human_task: { emoji: '👤', fallbackColor: '#f97316' },
  comment: { emoji: '✎', fallbackColor: '#eab308' },
  api_plugin: { emoji: '⌗', fallbackColor: '#f59e0b' },
  agent_loop: { emoji: '◉', fallbackColor: '#8b5cf6' },
  break: { emoji: '‖', fallbackColor: '#64748b' },
  continue: { emoji: '→', fallbackColor: '#64748b' },
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
