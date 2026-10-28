import { Drawer, Form, Input, InputNumber, Select, Space, Switch, Tag } from 'antd'
import { useEffect } from 'react'
import { useWorkflowStore, type WorkflowNodeType } from '../store/workflowStore'

interface Props {
  open: boolean
  onClose: () => void
  toolOptions?: Array<{ value: string; label: string }>
  documentOptions?: Array<{ value: string; label: string; disabled?: boolean }>
}

const TYPE_TITLE: Record<WorkflowNodeType, string> = {
  start: 'Start 节点',
  llm: 'LLM 节点',
  tool: 'Tool 节点',
  end: 'End 节点',
}

export function NodeConfigDrawer({
  open,
  onClose,
  toolOptions = [],
  documentOptions = [],
}: Props) {
  const selectedNodeId = useWorkflowStore((s) => s.selectedNodeId)
  const node = useWorkflowStore((s) => s.nodes.find((n) => n.id === selectedNodeId) ?? null)
  const updateNodeConfig = useWorkflowStore((s) => s.updateNodeConfig)

  const [form] = Form.useForm()

  useEffect(() => {
    if (node) {
      form.setFieldsValue({ ...node.data.config })
    } else {
      form.resetFields()
    }
  }, [node, form])

  const handleValuesChange = (_: unknown, values: Record<string, unknown>) => {
    if (!node) return
    updateNodeConfig(node.id, { ...node.data.config, ...values })
  }

  const nodeType: WorkflowNodeType | null = node?.data.nodeType ?? null

  const retrievalEnabled: boolean =
    (node?.data.config?.retrieval as { enabled?: boolean } | undefined)?.enabled === true

  return (
    <Drawer
      title={nodeType ? TYPE_TITLE[nodeType] : '节点配置'}
      placement="right"
      width={380}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {node && nodeType ? (
        <Form
          form={form}
          layout="vertical"
          onValuesChange={handleValuesChange}
          initialValues={{ ...node.data.config }}
        >
          <Space direction="vertical" size={4}>
            <Tag color="default">节点 ID：{node.id}</Tag>
          </Space>

          {nodeType === 'start' && (
            <Form.Item
              label="输出变量（JSON）"
              name="output_schema"
              extra="声明 Start 节点输出的 key/type 映射，例如 { query: 'string' }"
            >
              <Input.TextArea autoSize={{ minRows: 4 }} placeholder='{"query":"string"}' />
            </Form.Item>
          )}

          {nodeType === 'llm' && (
            <>
              <Form.Item label="模型 ID" name="model_id">
                <Input placeholder="default" />
              </Form.Item>
              <Form.Item
                label="System Prompt"
                name="system_prompt_tpl"
                extra="支持 {{query}} / {{node_id.field}} 模板"
              >
                <Input.TextArea autoSize={{ minRows: 3 }} />
              </Form.Item>
              <Form.Item label="User Prompt" name="user_prompt_tpl" rules={[{ required: true }]}>
                <Input.TextArea autoSize={{ minRows: 3 }} />
              </Form.Item>
              <Form.Item label="Temperature" name="temperature">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item label="Max Tokens" name="max_tokens">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>

              <Form.Item
                label="启用知识库检索（RAG）"
                name={['retrieval', 'enabled']}
                valuePropName="checked"
                extra="开启后，User Prompt 会作为 query 检索所选文档并拼接到 System Prompt"
              >
                <Switch />
              </Form.Item>
              {retrievalEnabled && (
                <Form.Item
                  label="选择文档"
                  name={['retrieval', 'document_ids']}
                  extra="仅展示本租户已启用且 ingest 完成的文档"
                >
                  <Select
                    mode="multiple"
                    options={documentOptions}
                    placeholder="选择知识库文档"
                    allowClear
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              )}
            </>
          )}

          {nodeType === 'tool' && (
            <>
              <Form.Item label="选择工具" name="tool_id" rules={[{ required: true }]}>
                <Select options={toolOptions} placeholder="从本租户工具表选择" allowClear />
              </Form.Item>
              <Form.Item
                label="参数模板（JSON）"
                name="arguments_tpl"
                extra="按所选工具的 input_schema 填充，value 支持 {{node_id.field}}"
              >
                <Input.TextArea
                  autoSize={{ minRows: 4 }}
                  placeholder='{"q":"{{llm_1.output}}"}'
                />
              </Form.Item>
            </>
          )}

          {nodeType === 'end' && (
            <Form.Item
              label="输出模板（JSON）"
              name="output_tpl"
              extra="最终返回给调用方的 outputs，例如 { answer: '{{llm_1.output}}' }"
            >
              <Input.TextArea autoSize={{ minRows: 4 }} placeholder='{"answer":"{{llm_1.output}}"}' />
            </Form.Item>
          )}
        </Form>
      ) : (
        <div style={{ color: '#8c8c8c', textAlign: 'center', padding: 40 }}>
          选中画布中的节点以编辑配置
        </div>
      )}
    </Drawer>
  )
}
