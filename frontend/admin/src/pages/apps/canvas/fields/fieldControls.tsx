import { Input, InputNumber, Select, Space } from 'antd'
import type { DatasetItem } from '../../../../api/datasets'
import { CANVAS_TOKENS } from '../tokens'
import { RefChipInput } from '../../components/RefChipInput'
import { CodeEditor } from '../../components/CodeEditor'
import { ParameterListEditor, type ParameterItem } from '../../components/ParameterListEditor'

// ========== 字段控件注册表（E2c） ==========
// 新增基础字段类型只需在此加一行，不再改 NodeConfigForm 的分支。
export interface FieldMeta {
  name: string
  label: string
  field_type: string
  options: Array<{ value: string; label?: string }>
  default: any
  required: boolean
  placeholder: string
  description: string
}

interface FieldControlProps {
  field: FieldMeta
  value: any
  onChange: (name: string, value: any) => void
  picker?: React.ReactNode
  datasetOptions?: DatasetItem[]
  // parameter_list 专用：内置锁定行（不写入 value）与是否允许添加
  lockedParams?: ParameterItem[]
  allowAdd?: boolean
}

type FieldRenderer = (props: FieldControlProps) => React.ReactNode

const FIELD_CONTROLS: Record<string, FieldRenderer> = {
  number: ({ field, value, onChange }) => {
    const current = value ?? field.default ?? ''
    return (
      <InputNumber
        value={typeof current === 'number' ? current : Number(current) || 0}
        onChange={(v) => onChange(field.name, v ?? 0)}
        style={{ width: '100%' }}
      />
    )
  },
  select: ({ field, value, onChange }) => {
    const current = value ?? field.default ?? ''
    return (
      <Select
        value={String(current || field.default || '')}
        onChange={(v) => onChange(field.name, v)}
        options={field.options.map((o) => ({ value: o.value, label: o.label || o.value }))}
        style={{ width: '100%' }}
      />
    )
  },
  boolean: ({ field, value, onChange }) => {
    const current = value ?? field.default ?? ''
    return (
      <Select
        value={current ? 'true' : 'false'}
        onChange={(v) => onChange(field.name, v === 'true')}
        options={[
          { value: 'true', label: '是' },
          { value: 'false', label: '否' },
        ]}
        style={{ width: '100%' }}
      />
    )
  },
  code_editor: ({ field, value, onChange, picker }) => (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {picker}
      <CodeEditor
        value={String(value ?? field.default ?? '')}
        onChange={(next) => onChange(field.name, next)}
        placeholder={field.placeholder}
      />
    </Space>
  ),
  parameter_list: ({ field, value, onChange, lockedParams, allowAdd }) => (
    <ParameterListEditor
      value={value}
      onChange={(next) => onChange(field.name, next)}
      lockedItems={lockedParams}
      allowAdd={allowAdd}
    />
  ),
  textarea: ({ field, value, onChange, picker }) => (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {picker}
      <Input.TextArea
        rows={4}
        value={String(value ?? field.default ?? '')}
        onChange={(e) => onChange(field.name, e.target.value)}
        placeholder={field.placeholder}
      />
    </Space>
  ),
  text: ({ field, value, onChange, picker, datasetOptions }) => {
    const current = value ?? field.default ?? ''
    if (field.name === 'datasetId') {
      return (
        <Select
          value={String(current || '') || undefined}
          onChange={(v) => onChange(field.name, v)}
          placeholder="选择知识库"
          style={{ width: '100%' }}
          options={(datasetOptions || []).map((d) => ({ value: d.id, label: d.title }))}
          notFoundContent="暂无知识库文档"
        />
      )
    }
    const isUrl = field.name === 'url'
    return (
      <Space direction="vertical" size={2} style={{ width: '100%' }}>
        <RefChipInput
          value={String(current || '')}
          onChange={(v) => onChange(field.name, v)}
          placeholder={field.placeholder}
          picker={picker}
          highlightPathParams={isUrl}
        />
        {isUrl && (
          <div style={{ fontSize: 11, color: '#9ca3af' }}>
            支持变量参数：https://api.example.com/users/
            <span style={{ color: CANVAS_TOKENS.accent }}>{'{{node.output.id}}'}</span>
          </div>
        )}
      </Space>
    )
  },
}

// 未注册的类型按文本渲染，保证新增字段类型不会直接崩掉
export function FieldControl(props: FieldControlProps) {
  const Renderer = FIELD_CONTROLS[props.field.field_type] ?? FIELD_CONTROLS.text!
  return <>{Renderer(props)}</>
}
