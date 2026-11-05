import { useState } from 'react'
import { CheckOutlined, CopyOutlined, FileDoneOutlined } from '@ant-design/icons'
import { AssistantContent } from '../../chat/components/AssistantContent'
import '../../chat/chat.css'

function unwrapOutput(output: unknown): unknown {
  if (output && typeof output === 'object' && !Array.isArray(output)) {
    const keys = Object.keys(output as Record<string, unknown>)
    if (keys.length === 1 && keys[0] === 'output') {
      return (output as Record<string, unknown>).output
    }
  }
  return output
}

function outputToText(output: unknown): string {
  if (typeof output === 'string') return output
  if (output === null || output === undefined) return ''
  try {
    return JSON.stringify(output, null, 2)
  } catch {
    return String(output)
  }
}

interface ResultCardProps {
  output: unknown
}

/** 运行结果卡：字符串按 markdown 渲染（复用 chat 组件），其余 JSON 展示，支持复制。 */
export default function ResultCard(props: ResultCardProps) {
  const value = unwrapOutput(props.output)
  const [copied, setCopied] = useState(false)
  const text = outputToText(value)
  const isString = typeof value === 'string'
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="wf-result">
      <div className="wf-result__head">
        <FileDoneOutlined />
        运行结果
        <button type="button" className="wf-result__copy" onClick={() => void copy()}>
          {copied ? <CheckOutlined /> : <CopyOutlined />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <div className="wf-result__body">
        {text === '' ? (
          <div className="wf-result__output wf-result__output--empty">本次运行无输出</div>
        ) : isString ? (
          <AssistantContent content={text} />
        ) : (
          <pre className="wf-result__json">{text}</pre>
        )}
      </div>
    </div>
  )
}
