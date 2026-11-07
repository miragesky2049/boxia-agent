import { ArrowUpOutlined, CloseOutlined, PictureOutlined } from '@ant-design/icons'
import { useEffect, useRef, useState } from 'react'

interface ComposerProps {
  value: string
  streaming?: boolean
  disabled?: boolean
  placeholder?: string
  onChange: (value: string) => void
  onSend: () => void
  onStop?: () => void
  /** 0074 PRD F9：随消息发送的图片 URL（粘贴式，应用 visionEnabled 时展示入口） */
  images?: string[]
  imagesEnabled?: boolean
  maxImages?: number
  onAddImage?: (url: string) => void
  onRemoveImage?: (index: number) => void
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
  images,
  imagesEnabled,
  maxImages = 8,
  onAddImage,
  onRemoveImage,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [imageDraft, setImageDraft] = useState('')

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  const canSend = value.trim().length > 0

  const addImage = () => {
    const url = imageDraft.trim()
    if (!url) return
    onAddImage?.(url)
    setImageDraft('')
  }

  return (
    <div className="lc-composer-area">
      {imagesEnabled && (
        <div className="lc-composer__images">
          {(images ?? []).map((url, index) => (
            <span key={url} className="lc-img-chip" title={url}>
              <PictureOutlined />
              <span className="lc-img-chip__text">{url}</span>
              <button
                type="button"
                aria-label="移除图片"
                onClick={() => onRemoveImage?.(index)}
              >
                <CloseOutlined />
              </button>
            </span>
          ))}
          {(images ?? []).length < maxImages && (
            <input
              className="lc-img-input"
              value={imageDraft}
              placeholder="粘贴图片链接，回车添加"
              onChange={(event) => setImageDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  addImage()
                }
              }}
              onBlur={addImage}
            />
          )}
        </div>
      )}
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
