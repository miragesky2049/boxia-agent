import { Card, Col, Form, Input, InputNumber, Row, Select } from 'antd'

export default function PromptSection() {
  return (
    <Card id="section-prompt" title="角色与提示词" className="config-card">
      <Form.Item name={['config', 'prompt', 'role_setting']} label="角色设定">
        <Input.TextArea rows={4} placeholder="描述智能体的角色、职责与行为边界" maxLength={50000} />
      </Form.Item>
      <Form.Item name={['config', 'prompt', 'persona']} label="人设描述">
        <Input.TextArea rows={3} placeholder="语气、风格与性格特征" maxLength={20000} />
      </Form.Item>
      <Form.Item name={['config', 'prompt', 'user_prompt']} label="用户提示词">
        <Input.TextArea rows={3} placeholder="每次对话附加的用户侧提示词" maxLength={20000} />
      </Form.Item>
      <Row gutter={20}>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'prompt', 'memory_count']} label="记忆轮数">
            <InputNumber min={0} max={200} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'prompt', 'memory_model']} label="记忆摘要模型">
            <Select
              options={[
                { label: 'GLM-5', value: 'glm-5' },
                { label: 'GLM-4.5', value: 'glm-4.5' },
                { label: 'GPT-4o', value: 'gpt-4o' },
              ]}
            />
          </Form.Item>
        </Col>
      </Row>
    </Card>
  )
}
