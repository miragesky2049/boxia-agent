import { ArrowUpOutlined } from '@ant-design/icons'
import { useEffect, useRef } from 'react'

interface ComposerProps {
  value: string
  streaming?: boolean
  disabled?: boolean
  placeholder?: string
  onChange: (value: string) => void
  onSend: () => void
  onStop?: () => void
}

const MAX_HEIGHT = 200

export function Composer({
  value,
  streaming,
  disabled,
  placeholder = '有什么可以帮你？',
  onChange,
  onSend,
  onStop,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  const canSend = value.trim().length > 0

  return (
    <div className="lc-composer-area">
      <div className="lc-composer">
        <textarea
          ref={textareaRef}
          className="lc-composer__input"
          rows={1}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === 'Enter' &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault()
              if (canSend) onSend()
            }
          }}
        />

        {streaming ? (
          <button
            type="button"
            className="lc-send is-stop"
            onClick={onStop}
            aria-label="停止生成"
          >
            <span className="lc-stop-square" aria-hidden />
          </button>
        ) : (
          <button
            type="button"
            className="lc-send"
            disabled={!canSend || disabled}
            onClick={onSend}
            aria-label="发送"
          >
            <ArrowUpOutlined />
          </button>
        )}
      </div>
      <p className="lc-composer__tip">
        Enter 发送，Shift + Enter 换行 · 内容由 AI 生成，请谨慎甄别
      </p>
    </div>
  )
}
