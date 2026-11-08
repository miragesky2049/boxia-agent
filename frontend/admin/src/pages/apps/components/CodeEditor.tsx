import { useMemo } from 'react'
import Editor from 'react-simple-code-editor'

// 轻量 Python 语法高亮：关键字 / 字符串 / 注释 / 数字，不引 prismjs
const PY_KEYWORDS = new Set([
  'def',
  'return',
  'if',
  'elif',
  'else',
  'for',
  'while',
  'in',
  'not',
  'and',
  'or',
  'import',
  'from',
  'as',
  'with',
  'try',
  'except',
  'finally',
  'raise',
  'class',
  'None',
  'True',
  'False',
  'lambda',
  'pass',
  'break',
  'continue',
  'yield',
  'global',
  'nonlocal',
  'assert',
  'del',
  'is',
  'async',
  'await',
])

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function highlightPython(code: string): string {
  // 先按 token 切分：注释、字符串、数字、单词、其他
  const re =
    /(#.*$)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|.)/gm
  let out = ''
  let m: RegExpExecArray | null
  while ((m = re.exec(code)) !== null) {
    const [, comment, str, num, word, other] = m
    if (comment) {
      out += `<span style="color:#6a9955">${escapeHtml(comment)}</span>`
    } else if (str) {
      out += `<span style="color:#ce9178">${escapeHtml(str)}</span>`
    } else if (num) {
      out += `<span style="color:#b5cea8">${escapeHtml(num)}</span>`
    } else if (word) {
      if (PY_KEYWORDS.has(word)) {
        out += `<span style="color:#569cd6">${escapeHtml(word)}</span>`
      } else {
        out += escapeHtml(word)
      }
    } else if (other) {
      out += escapeHtml(other)
    }
  }
  return out
}

export function CodeEditor({
  value,
  onChange,
  placeholder,
}: {
  value: string
  onChange: (next: string) => void
  placeholder?: string
}) {
  const highlight = useMemo(() => highlightPython, [])
  return (
    <div
      style={{
        background: '#1e1e2e',
        borderRadius: 6,
        border: '1px solid #313244',
        overflow: 'hidden',
      }}
    >
      <Editor
        value={value}
        onValueChange={onChange}
        highlight={highlight}
        padding={10}
        placeholder={placeholder}
        style={{
          fontFamily: 'Menlo, Monaco, Consolas, monospace',
          fontSize: 12,
          background: '#1e1e2e',
          color: '#cdd6f4',
          minHeight: 200,
          outline: 'none',
        }}
        textareaClassName="code-editor-textarea"
        preClassName="code-editor-pre"
      />
      <style>{`
        .code-editor-textarea, .code-editor-pre {
          margin: 0 !important;
          white-space: pre !important;
          word-wrap: normal !important;
          overflow: auto !important;
        }
        .code-editor-textarea {
          outline: none;
        }
      `}</style>
    </div>
  )
}
