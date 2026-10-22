import { Card, Form, Select, Switch } from 'antd'

export default function KnowledgeSection() {
  return (
    <Card id="section-knowledge" title="知识库" className="config-card">
      <Form.Item
        name={['config', 'knowledge', 'enabled']}
        label="启用知识库"
        valuePropName="checked"
      >
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item
        name={['config', 'knowledge', 'dataset_ids']}
        label="关联知识库"
        extra="输入知识库 ID 后回车，可关联多个"
      >
        <Select mode="tags" placeholder="例如：dataset-001" />
      </Form.Item>
    </Card>
  )
}
