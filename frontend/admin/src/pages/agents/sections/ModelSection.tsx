import { Card, Col, Form, InputNumber, Row, Select } from 'antd'

const MODEL_OPTIONS = [
  { label: 'GLM-5', value: 'glm-5' },
  { label: 'GLM-4.5', value: 'glm-4.5' },
  { label: 'GPT-4o', value: 'gpt-4o' },
  { label: 'Claude Sonnet 4.6', value: 'claude-sonnet-4-6' },
  { label: 'DeepSeek V3', value: 'deepseek-v3' },
]

export default function ModelSection() {
  return (
    <Card id="section-model" title="模型配置" className="config-card">
      <Row gutter={20}>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'model', 'model']} label="选择模型">
            <Select options={MODEL_OPTIONS} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'model', 'temperature']} label="温度（0 - 2）">
            <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'model', 'max_output_tokens']} label="最大输出 Token">
            <InputNumber min={1} max={200000} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'model', 'reasoning_effort']} label="推理强度">
            <Select
              options={[
                { label: '低', value: 'low' },
                { label: '中', value: 'medium' },
                { label: '高', value: 'high' },
              ]}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'model', 'context_window']} label="上下文窗口">
            <InputNumber min={1} max={2000000} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'model', 'max_thinking_tokens']} label="最大思考 Token">
            <InputNumber min={0} max={200000} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
    </Card>
  )
}
