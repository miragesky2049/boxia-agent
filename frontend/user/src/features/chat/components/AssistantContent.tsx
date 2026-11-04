import { CheckOutlined, CopyOutlined } from '@ant-design/icons'
import { useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { highlightCode } from '../highlight'

interface CodeBlockProps {
  code: string
  lang?: string
}

function CodeBlock({ code, lang }: CodeBlockProps) {
  const [copied, setCopied] = useState(false)
  const highlighted = useMemo(() => highlightCode(code, lang), [code, lang])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="lc-code">
      <div className="lc-code__bar">
        <span className="lc-code__lang">{lang || 'text'}</span>
        <button type="button" className="lc-code__copy" onClick={handleCopy}>
          {copied ? <CheckOutlined /> : <CopyOutlined />}
          <span>{copied ? '已复制' : '复制'}</span>
        </button>
      </div>
      <pre className="lc-code__pre">
        <code className="hljs" dangerouslySetInnerHTML={{ __html: highlighted }} />
      </pre>
    </div>
  )
}

interface AssistantContentProps {
  content: string
  streaming?: boolean
}

export function AssistantContent({ content, streaming }: AssistantContentProps) {
  return (
    <div className="lc-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre({ children }) {
            return <>{children}</>
          },
          code({ className, children }) {
            const match = /language-(\w+)/.exec(className || '')
            if (match) {
              return (
                <CodeBlock
                  lang={match[1]}
                  code={String(children).replace(/\n$/, '')}
                />
              )
            }
            return <code className="lc-inline-code">{children}</code>
          },
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
      {streaming && <span className="lc-cursor" aria-hidden />}
    </div>
  )
}
