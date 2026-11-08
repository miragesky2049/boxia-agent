import { useMemo } from 'react'
import { Input } from 'antd'

interface RefChipInputProps {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  picker?: React.ReactNode
  // URL 字段启用：把 :param 形式的路径参数渲染为橙色 chip
  highlightPathParams?: boolean
}

type SegmentType = 'text' | 'ref' | 'pathparam'
interface Segment {
  type: SegmentType
  value: string
}

// 切分文本为普通片段 / {{ref}} 引用片段 / :param 路径参数片段
function splitSegments(text: string, highlightPathParams?: boolean): Segment[] {
  if (!text) return []
  const segments: Segment[] = []
  const patterns: Array<{ type: SegmentType; regex: RegExp }> = [
    { type: 'ref', regex: /\{\{[^}]+\}\}/g },
  ]
  if (highlightPathParams) {
    patterns.push({ type: 'pathparam', regex: /:[A-Za-z_][A-Za-z0-9_]*/g })
  }

  // 收集所有匹配并按位置排序
  const matches: Array<{ type: SegmentType; index: number; value: string }> = []
  for (const { type, regex } of patterns) {
    let m: RegExpExecArray | null
    regex.lastIndex = 0
    while ((m = regex.exec(text)) !== null) {
      matches.push({ type, index: m.index, value: m[0] })
    }
  }
  matches.sort((a, b) => a.index - b.index || b.value.length - a.value.length)

  let lastIndex = 0
  for (const match of matches) {
    if (match.index < lastIndex) continue // 重叠匹配，跳过
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, match.index) })
    }
    segments.push({ type: match.type, value: match.value })
    lastIndex = match.index + match.value.length
  }
  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) })
  }
  return segments
}

function removeRef(text: string, ref: string): string {
  return text.split(ref).join('')
}

// RefChipInput（U-I1）：单行输入 + 内联引用胶囊预览
// 上方是可编辑的 Input（用户输入纯文本），下方是同边框容器内的预览：
// 普通文本片段渲染为普通 span，{{ref}} 片段渲染为蓝色 monospace 胶囊（可点 × 删除）
// :param 片段（highlightPathParams=true 时）渲染为橙色 monospace 胶囊（不可删，仅高亮）
export function RefChipInput({
  value,
  onChange,
  placeholder,
  picker,
  highlightPathParams,
}: RefChipInputProps) {
  const segments = useMemo(
    () => splitSegments(value || '', highlightPathParams),
    [value, highlightPathParams],
  )
  const hasChip = segments.some((s) => s.type !== 'text')

  return (
    <div
      style={{
        border: '1px solid #d9d9d9',
        borderRadius: 6,
        padding: '4px 11px',
        background: '#fff',
        transition: 'border-color 0.2s, box-shadow 0.2s',
      }}
      className="boxia-ref-chip-input"
    >
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        variant="borderless"
        style={{ padding: 0 }}
        suffix={picker}
      />
      {hasChip && (
        <div
          style={{
            marginTop: 4,
            paddingTop: 4,
            borderTop: '1px dashed #e5e7eb',
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            gap: 2,
            fontSize: 12,
            lineHeight: '22px',
          }}
        >
          {segments.map((seg, idx) => {
            if (seg.type === 'text') {
              return (
                <span key={idx} style={{ color: '#111827', whiteSpace: 'pre-wrap' }}>
                  {seg.value}
                </span>
              )
            }
            if (seg.type === 'pathparam') {
              // :param 路径参数：橙色胶囊，仅高亮不可删
              return (
                <span
                  key={idx}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    background: '#fff7ed',
                    color: '#ea580c',
                    fontFamily: 'Menlo, Monaco, Consolas, monospace',
                    padding: '0 6px',
                    borderRadius: 4,
                    lineHeight: '20px',
                    margin: '0 2px',
                  }}
                >
                  {seg.value}
                </span>
              )
            }
            const inner = seg.value.slice(2, -2)
            return (
              <span
                key={idx}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  background: '#eef2ff',
                  color: '#4f46e5',
                  fontFamily: 'Menlo, Monaco, Consolas, monospace',
                  padding: '0 6px',
                  borderRadius: 4,
                  lineHeight: '20px',
                  margin: '0 2px',
                }}
              >
                {inner}
                <button
                  type="button"
                  onClick={() => onChange(removeRef(value, seg.value))}
                  style={{
                    border: 'none',
                    background: 'transparent',
                    color: '#4f46e5',
                    cursor: 'pointer',
                    padding: 0,
                    fontSize: 12,
                    lineHeight: 1,
                  }}
                  aria-label={`删除引用 ${inner}`}
                >
                  ×
                </button>
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
