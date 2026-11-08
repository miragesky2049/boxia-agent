// 画布语义令牌：色值取自 Coze 实机采样，集中维护。
// 约定（E3）：画布相关的同义色值只允许出现在本文件，组件通过 CANVAS_TOKENS 引用。
export const CANVAS_TOKENS = {
  // 连线
  line: '#5044fc',
  lineHover: '#3f33e0',
  lineActive: '#22c1e8',
  lineActiveGlow: 'rgba(34,193,232,0.5)',

  // 端口
  port: '#6366f1',
  portHover: '#4338ca',
  portLinked: '#4d53e8',
  portDrop: '#4f46e5',
  portRing: 'rgba(99,102,241,0.15)',
  portRingSoft: 'rgba(99,102,241,0.1)',
  portDropRing: 'rgba(79,70,229,0.22)',

  // 品牌与辅助
  accent: '#6366f1',
  accentSoft: '#eef2ff',
  accentText: '#4f46e5',
  guide: '#6366f1',

  // 运行状态
  run: '#10b981',
  running: '#8b5cf6',
  runningGlow: 'rgba(139,92,246,0.15)',
  runningPulse: 'rgba(139,92,246,0.4)',
  danger: '#ef4444',
  dangerDeep: '#d4380d',
  dangerDot: '#ff4d4f',
  dangerGlow: 'rgba(239,68,68,0.5)',
  warning: '#f59e0b',
  info: '#3b82f6',

  // 结构
  border: '#e5e7eb',
  white: '#fff',

  // 层级
  z: { guides: 90, toolbar: 100, overlay: 120 },
} as const
