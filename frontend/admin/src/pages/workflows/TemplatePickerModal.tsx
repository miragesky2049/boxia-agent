import { InboxOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Empty, Input, Modal, Spin, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { listTemplates } from '../../api/workflows'
import type { WorkflowTemplate } from '../../api/workflows'

interface TemplatePickerModalProps {
  open: boolean
  onClose: () => void
  /** 选择模板后回调：父组件负责调用 clone 接口。 */
  onPickTemplate: (template: WorkflowTemplate, name: string) => void
  /** 选择"空白画布"：父组件直接用默认骨架创建。 */
  onPickBlank: (name: string) => void
}

export default function TemplatePickerModal({
  open,
  onClose,
  onPickTemplate,
  onPickBlank,
}: TemplatePickerModalProps) {
  const { message } = App.useApp()
  const [items, setItems] = useState<WorkflowTemplate[]>([])
  const [loading, setLoading] = useState(false)
  const [name, setName] = useState('')
  const [pickedId, setPickedId] = useState<string | 'blank' | null>(null)

  useEffect(() => {
    if (!open) return
    setPickedId(null)
    setName('')
    setLoading(true)
    listTemplates({ page: 1, page_size: 50 })
      .then((result) => setItems(result.items))
      .catch((error) =>
        message.error(error instanceof Error ? error.message : '加载模板失败'),
      )
      .finally(() => setLoading(false))
  }, [open, message])

  const handleOk = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      message.warning('请填写工作流名称')
      return
    }
    if (pickedId === 'blank') {
      onPickBlank(trimmed)
      return
    }
    const template = items.find((item) => item.id === pickedId)
    if (!template) {
      message.warning('请选择一个模板')
      return
    }
    onPickTemplate(template, trimmed)
  }

  return (
    <Modal
      title="新建工作流"
      open={open}
      width={720}
      okText="创建"
      cancelText="取消"
      onCancel={onClose}
      onOk={handleOk}
      okButtonProps={{ disabled: !pickedId || !name.trim() }}
      destroyOnClose
    >
      <Input
        placeholder="工作流名称（必填）"
        value={name}
        onChange={(event) => setName(event.target.value)}
        style={{ marginBottom: 16 }}
      />
      {loading ? (
        <div style={{ textAlign: 'center', padding: 48 }}>
          <Spin />
        </div>
      ) : (
        <div className="template-picker">
          <button
            type="button"
            className={`template-card ${pickedId === 'blank' ? 'template-card--active' : ''}`}
            onClick={() => setPickedId('blank')}
          >
            <PlusOutlined />
            <div className="template-card__title">空白画布</div>
            <div className="template-card__desc">
              从预置的 Start → LLM → End 骨架开始
            </div>
          </button>
          {items.length === 0 ? (
            <Empty description="暂无模板，可直接从空白画布开始" />
          ) : (
            items.map((template) => (
              <button
                type="button"
                key={template.id}
                className={`template-card ${pickedId === template.id ? 'template-card--active' : ''}`}
                onClick={() => setPickedId(template.id)}
              >
                <InboxOutlined />
                <div className="template-card__title">{template.name}</div>
                <div className="template-card__desc">
                  {template.description || '暂无描述'}
                </div>
                {template.category ? (
                  <Tag bordered={false} color="blue">
                    {template.category}
                  </Tag>
                ) : null}
              </button>
            ))
          )}
        </div>
      )}
    </Modal>
  )
}
