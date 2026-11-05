import { useEffect, useMemo, useState } from 'react'
import { DeleteOutlined, UploadOutlined } from '@ant-design/icons'
import type { WorkflowParam, WorkflowSchema } from '../types'

interface FileValue {
  name: string
  dataUrl: string
}

type RawValues = Record<string, string | FileValue[]>

const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_IMAGE_COUNT = 6

function emptyRaw(param: WorkflowParam): string | FileValue[] {
  return param.type === 'file' || param.type === 'image' ? [] : ''
}

function jsonPlaceholder(type: WorkflowParam['type']): string {
  switch (type) {
    case 'object':
      return '{"key": "value"}'
    case 'array[string]':
      return '["a", "b"]'
    case 'array[number]':
      return '[1, 2]'
    case 'array[object]':
      return '[{"key": "value"}]'
    default:
      return ''
  }
}

function defaultRaw(param: WorkflowParam): string | FileValue[] {
  if (param.default_value === null || param.default_value === undefined) return emptyRaw(param)
  if (param.type === 'file' || param.type === 'image') return []
  if (param.type === 'string' || param.type === 'number' || param.type === 'boolean') {
    return String(param.default_value)
  }
  try {
    return JSON.stringify(param.default_value, null, 2)
  } catch {
    return emptyRaw(param)
  }
}

function validateParam(param: WorkflowParam, raw: string | FileValue[]): string {
  if (param.type === 'file' || param.type === 'image') {
    const files = raw as FileValue[]
    if (param.required && files.length === 0) return `请上传${param.description || param.name}`
    if (param.type === 'image' && files.length > MAX_IMAGE_COUNT) return `最多上传 ${MAX_IMAGE_COUNT} 张图片`
    return ''
  }
  const text = (raw as string).trim()
  if (!text) return param.required ? `请填写${param.description || param.name}` : ''
  switch (param.type) {
    case 'number':
      return Number.isFinite(Number(text)) ? '' : '请输入合法数字'
    case 'boolean':
      return text === 'true' || text === 'false' ? '' : '请输入 true 或 false'
    case 'object':
      try {
        const parsed = JSON.parse(text) as unknown
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          return '请输入合法 JSON 对象'
        }
        return ''
      } catch {
        return 'JSON 解析失败'
      }
    case 'array[string]':
    case 'array[number]':
    case 'array[object]':
      try {
        const parsed = JSON.parse(text) as unknown
        return Array.isArray(parsed) ? '' : '请输入 JSON 数组'
      } catch {
        return 'JSON 解析失败'
      }
    default:
      return ''
  }
}

function buildInputValue(param: WorkflowParam, raw: string | FileValue[]): unknown {
  if (param.type === 'file') return (raw as FileValue[])[0]?.dataUrl ?? null
  if (param.type === 'image') return (raw as FileValue[]).map((f) => f.dataUrl)
  const text = (raw as string).trim()
  if (!text) return param.default_value ?? undefined
  switch (param.type) {
    case 'number':
      return Number(text)
    case 'boolean':
      return text === 'true'
    case 'string':
      return text
    default:
      return JSON.parse(text) as unknown
  }
}

function readFileAsDataUrl(file: File): Promise<FileValue> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve({ name: file.name, dataUrl: String(reader.result) })
    reader.onerror = () => reject(new Error(`读取文件失败：${file.name}`))
    reader.readAsDataURL(file)
  })
}

interface StartInputFormProps {
  schema: WorkflowSchema | null
  running: boolean
  onSubmit: (inputs: Record<string, unknown>) => void
}

/** 启动表单：按 schema 渲染九类入参控件，前端做必填/JSON/体积校验。 */
export default function StartInputForm(props: StartInputFormProps) {
  const { schema, running, onSubmit } = props
  const [raw, setRaw] = useState<RawValues>({})
  const [notice, setNotice] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    if (!schema) return
    const next: RawValues = {}
    for (const param of schema.inputs) next[param.name] = defaultRaw(param)
    setRaw(next)
    setNotice({})
    setTouched(false)
  }, [schema])

  const errors = useMemo(() => {
    const map: Record<string, string> = {}
    for (const [name, text] of Object.entries(notice)) {
      if (text) map[name] = text
    }
    if (!schema) return map
    for (const param of schema.inputs) {
      const err = validateParam(param, raw[param.name] ?? emptyRaw(param))
      if (err && !map[param.name]) map[param.name] = err
    }
    return map
  }, [schema, raw, notice])

  if (!schema) {
    return <p className="wf-form__hint">正在加载入参定义…</p>
  }

  const handleFiles = async (param: WorkflowParam, files: FileList | null) => {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    const oversized = list.find((f) => f.size > MAX_FILE_BYTES)
    if (oversized) {
      setNotice((prev) => ({ ...prev, [param.name]: `「${oversized.name}」超过 10MB，已忽略` }))
      return
    }
    const prev = ((raw[param.name] as FileValue[]) ?? []) as FileValue[]
    const capacity = param.type === 'image' ? MAX_IMAGE_COUNT - prev.length : 1
    const accepted = list.slice(0, Math.max(capacity, 0))
    if (accepted.length === 0) {
      setNotice((prev) => ({ ...prev, [param.name]: `最多上传 ${MAX_IMAGE_COUNT} 张图片` }))
      return
    }
    const loaded = await Promise.all(accepted.map(readFileAsDataUrl))
    setNotice((prev) => ({ ...prev, [param.name]: '' }))
    setRaw((state) => ({
      ...state,
      [param.name]: param.type === 'file' ? loaded.slice(-1) : [...prev, ...loaded],
    }))
  }

  const removeFile = (param: WorkflowParam, index: number) => {
    const prev = ((raw[param.name] as FileValue[]) ?? []) as FileValue[]
    setRaw((state) => ({ ...state, [param.name]: prev.filter((_, i) => i !== index) }))
  }

  const submit = () => {
    setTouched(true)
    if (running || Object.keys(errors).length > 0) return
    const inputs: Record<string, unknown> = {}
    for (const param of schema.inputs) {
      const value = buildInputValue(param, raw[param.name] ?? emptyRaw(param))
      if (value !== undefined) inputs[param.name] = value
    }
    onSubmit(inputs)
  }

  return (
    <form
      className="wf-form"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      {schema.inputs.map((param) => (
        <StartField
          key={param.name}
          param={param}
          raw={raw[param.name] ?? emptyRaw(param)}
          error={touched ? errors[param.name] : undefined}
          onText={(v) => {
            setNotice((prev) => ({ ...prev, [param.name]: '' }))
            setRaw((state) => ({ ...state, [param.name]: v }))
          }}
          onFiles={(files) => void handleFiles(param, files)}
          onRemoveFile={(i) => removeFile(param, i)}
        />
      ))}
      <div className="wf-form__footer">
        <button type="submit" className="wf-btn wf-btn--primary wf-btn--block" disabled={running}>
          {running ? '运行中…' : '开始运行'}
        </button>
        <p className="wf-form__hint">
          运行过程将实时展示各节点轨迹；如流程包含人工审批，可在对应角色账号中处理。
        </p>
      </div>
    </form>
  )
}

interface StartFieldProps {
  param: WorkflowParam
  raw: string | FileValue[]
  error?: string
  onText: (value: string) => void
  onFiles: (files: FileList | null) => void
  onRemoveFile: (index: number) => void
}

function StartField(props: StartFieldProps) {
  const { param, raw, error, onText, onFiles, onRemoveFile } = props
  const text = typeof raw === 'string' ? raw : ''
  const files = Array.isArray(raw) ? raw : []
  return (
    <div className="wf-field">
      <label className="wf-field__label" htmlFor={`wf-param-${param.name}`}>
        {param.name}
        {param.required ? <span className="wf-field__required">*</span> : null}
        <span className="wf-field__type">{param.type}</span>
      </label>
      {param.description ? <p className="wf-field__desc">{param.description}</p> : null}
      <div className="wf-field__control">
        <ParamControl
          param={param}
          text={text}
          files={files}
          onText={onText}
          onFiles={onFiles}
          onRemoveFile={onRemoveFile}
        />
      </div>
      {error ? <div className="wf-field__error">{error}</div> : null}
    </div>
  )
}

interface ParamControlProps {
  param: WorkflowParam
  text: string
  files: FileValue[]
  onText: (value: string) => void
  onFiles: (files: FileList | null) => void
  onRemoveFile: (index: number) => void
}

function ParamControl(props: ParamControlProps) {
  const { param, text, files, onText, onFiles, onRemoveFile } = props
  const id = `wf-param-${param.name}`
  switch (param.type) {
    case 'number':
    case 'boolean':
      return (
        <input
          id={id}
          className="wf-textarea"
          style={{ minHeight: 38 }}
          value={text}
          placeholder={param.type === 'boolean' ? 'true / false' : '0'}
          onChange={(e) => onText(e.target.value)}
        />
      )
    case 'object':
    case 'array[string]':
    case 'array[number]':
    case 'array[object]':
      return (
        <textarea
          id={id}
          className="wf-textarea"
          value={text}
          placeholder={jsonPlaceholder(param.type)}
          spellCheck={false}
          onChange={(e) => onText(e.target.value)}
        />
      )
    case 'file':
      return (
        <div className="wf-upload">
          <label className="wf-btn wf-btn--ghost" htmlFor={`${id}-file`} style={{ alignSelf: 'flex-start' }}>
            <UploadOutlined />
            上传文件
          </label>
          <input
            id={`${id}-file`}
            type="file"
            hidden
            onChange={(e) => {
              onFiles(e.target.files)
              e.target.value = ''
            }}
          />
          {files.map((f, i) => (
            <span key={i} className="wf-file-chip">
              <span>{f.name}</span>
              <button
                type="button"
                className="wf-link-btn"
                aria-label="移除文件"
                onClick={() => onRemoveFile(i)}
              >
                <DeleteOutlined />
              </button>
            </span>
          ))}
        </div>
      )
    case 'image':
      return (
        <div className="wf-upload">
          <label className="wf-btn wf-btn--ghost" htmlFor={`${id}-image`} style={{ alignSelf: 'flex-start' }}>
            <UploadOutlined />
            上传图片（最多 {MAX_IMAGE_COUNT} 张）
          </label>
          <input
            id={`${id}-image`}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => {
              onFiles(e.target.files)
              e.target.value = ''
            }}
          />
          <div className="wf-upload__previews">
            {files.map((f, i) => (
              <div key={i} className="wf-upload__thumb">
                <img src={f.dataUrl} alt={f.name} />
                <button
                  type="button"
                  className="wf-upload__remove"
                  aria-label="移除图片"
                  onClick={() => onRemoveFile(i)}
                >
                  <DeleteOutlined />
                </button>
              </div>
            ))}
          </div>
        </div>
      )
    case 'string':
    default:
      return <textarea id={id} className="wf-textarea" value={text} onChange={(e) => onText(e.target.value)} />
  }
}
