import {
  CheckCircleFilled,
  CloseOutlined,
  FileOutlined,
  InboxOutlined,
  LoadingOutlined,
} from '@ant-design/icons'
import { Button, Progress, Tag, message } from 'antd'
import { useCallback, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import type {
  UploadedMaterialFile,
  UploadMaterialProps,
  UploadMaterialRequest,
} from './types'
import './senclaw-cmp.css'

let fileSeq = 0
function nextFileId(): string {
  fileSeq += 1
  return `um_${Date.now()}_${fileSeq}`
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/**
 * 内置模拟上传：后端 GetSceneRobotDataMdContext 链路未就绪前用于前端联调。
 * 真实环境由调用方通过 uploadRequest 注入。
 */
const simulateUpload: UploadMaterialRequest = (file) => {
  const duration = 900 + Math.random() * 900
  return new Promise((resolve, reject) => {
    window.setTimeout(() => {
      if (file.size === 0) {
        reject(new Error('文件内容为空'))
        return
      }
      resolve({ materialId: `mat_${nextFileId()}` })
    }, duration)
  })
}

const ACCEPT_ATTR = '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.csv,.png,.jpg,.jpeg'

export default function UploadMaterial(props: UploadMaterialProps) {
  const {
    sceneRobotId,
    disabled = false,
    onUploaded,
    onSkip,
    uploadRequest,
    style,
    className,
  } = props

  const [files, setFiles] = useState<UploadedMaterialFile[]>([])
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const notifiedRef = useRef(false)

  const patchFile = useCallback((id: string, patch: Partial<UploadedMaterialFile>) => {
    setFiles((prev) =>
      prev.map((f) => (f.id === id ? { ...f, ...patch } : f)),
    )
  }, [])

  const removeFile = useCallback(
    (id: string) => {
      if (disabled) return
      setFiles((prev) => prev.filter((f) => f.id !== id))
    },
    [disabled],
  )

  const notifyIfAllDone = useCallback(
    (next: UploadedMaterialFile[]) => {
      if (notifiedRef.current) return
      if (next.length === 0) return
      const finished = next.every((f) => f.status === 'done' || f.status === 'error')
      if (finished) {
        notifiedRef.current = true
        onUploaded?.(next)
      }
    },
    [onUploaded],
  )

  const runUpload = useCallback(
    async (file: File) => {
      const id = nextFileId()
      const meta: UploadedMaterialFile = {
        id,
        name: file.name,
        size: file.size,
        status: 'uploading',
      }
      setFiles((prev) => {
        const next = [...prev, meta]
        notifyIfAllDone(next)
        return next
      })

      const requester = uploadRequest ?? simulateUpload
      try {
        const { materialId } = await requester(file, sceneRobotId)
        patchFile(id, { status: 'parsing' })
        // 后端解析延迟模拟：真实链路中 requester 返回后即代表解析完成
        await new Promise((r) => window.setTimeout(r, 600 + Math.random() * 600))
        patchFile(id, { status: 'done', materialId })
        setFiles((prev) => {
          notifyIfAllDone(prev)
          return prev
        })
      } catch (err) {
        patchFile(id, {
          status: 'error',
          error: err instanceof Error ? err.message : '上传失败',
        })
        setFiles((prev) => {
          notifyIfAllDone(prev)
          return prev
        })
      }
    },
    [notifyIfAllDone, patchFile, sceneRobotId, uploadRequest],
  )

  const acceptFiles = useCallback(
    (list: FileList | File[]) => {
      if (disabled) return
      Array.from(list).forEach((f) => {
        if (!f) return
        void runUpload(f)
      })
    },
    [disabled, runUpload],
  )

  const handleInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      acceptFiles(e.target.files)
    }
    // 重置 input，允许重复选择同一文件
    e.target.value = ''
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (disabled) return
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      acceptFiles(e.dataTransfer.files)
    }
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    if (disabled) return
    setDragActive(true)
  }

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
  }

  const handleSkip = () => {
    if (disabled) return
    message.info('已跳过资料上传')
    onSkip?.()
  }

  const uploadingCount = files.filter((f) => f.status === 'uploading').length
  const parsingCount = files.filter((f) => f.status === 'parsing').length
  const busy = uploadingCount > 0 || parsingCount > 0

  return (
    <div
      className={`um-card ${className ?? ''}`}
      style={style}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <div
        className={`um-drop ${dragActive ? 'um-drop--active' : ''} ${disabled ? 'um-drop--disabled' : ''}`}
        onClick={() => {
          if (disabled) return
          inputRef.current?.click()
        }}
        role="button"
        aria-label="上传资料"
      >
        <div className="um-drop__icon">
          <InboxOutlined />
        </div>
        <div className="um-drop__title">点击或拖拽文件到此处上传</div>
        <div className="um-drop__hint">
          支持 PDF / Word / Excel / PPT / TXT / Markdown / 图片，单次可上传多个
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          style={{ display: 'none' }}
          onChange={handleInputChange}
          disabled={disabled}
        />
      </div>

      {files.length > 0 && (
        <div className="um-file-list">
          {files.map((f) => (
            <div key={f.id} className="um-file">
              <span className="um-file__icon">
                <FileOutlined />
              </span>
              <span className="um-file__name" title={f.name}>
                {f.name}
              </span>
              <span className="um-file__size">{formatSize(f.size)}</span>
              <span className="um-file__status">
                {f.status === 'uploading' && (
                  <Tag icon={<LoadingOutlined />} color="blue">
                    上传中
                  </Tag>
                )}
                {f.status === 'parsing' && (
                  <Tag icon={<LoadingOutlined />} color="processing">
                    解析中
                  </Tag>
                )}
                {f.status === 'done' && (
                  <Tag icon={<CheckCircleFilled />} color="success">
                    已就绪
                  </Tag>
                )}
                {f.status === 'error' && (
                  <Tag color="error" title={f.error}>
                    失败
                  </Tag>
                )}
              </span>
              {!disabled && !busy && (
                <button
                  type="button"
                  className="um-file__remove"
                  aria-label="移除文件"
                  onClick={() => removeFile(f.id)}
                >
                  <CloseOutlined />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {busy && (
        <div className="um-progress">
          <Progress
            percent={Math.round(((files.length - uploadingCount) / Math.max(files.length, 1)) * 100)}
            size="small"
            status="active"
          />
        </div>
      )}

      <div className="um-actions">
        <Button type="text" size="small" disabled={disabled || busy} onClick={handleSkip}>
          跳过资料
        </Button>
      </div>
    </div>
  )
}
