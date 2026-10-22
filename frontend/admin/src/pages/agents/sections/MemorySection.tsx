import { Card, Form, Input, Switch } from 'antd'

export default function MemorySection() {
  return (
    <Card id="section-memory" title="记忆配置" className="config-card">
      <Form.Item
        name={['config', 'memory', 'enabled']}
        label="启用任务记忆"
        valuePropName="checked"
      >
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item name={['config', 'memory', 'task_memory_prompt']} label="任务记忆提示词">
        <Input.TextArea rows={3} placeholder="用于引导模型提取任务记忆" maxLength={10000} />
      </Form.Item>
      <Form.Item
        name={['config', 'memory', 'long_term_enabled']}
        label="启用长期记忆"
        valuePropName="checked"
      >
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>
      <Form.Item name={['config', 'memory', 'long_term_prompt']} label="长期记忆提示词">
        <Input.TextArea rows={3} placeholder="用于引导模型沉淀长期记忆" maxLength={10000} />
      </Form.Item>
    </Card>
  )
}
