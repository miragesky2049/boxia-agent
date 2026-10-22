import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Card, Col, Form, Input, Row, Switch } from 'antd'

export default function ConversationSection() {
  return (
    <Card id="section-conversation" title="对话体验" className="config-card">
      <Form.Item name={['config', 'conversation', 'welcome']} label="欢迎语">
        <Input.TextArea rows={2} placeholder="用户进入对话时展示的第一句话" maxLength={2000} />
      </Form.Item>
      <Form.Item name={['config', 'conversation', 'fallback']} label="兜底回复">
        <Input.TextArea rows={2} placeholder="无法识别用户意图时的默认回复" maxLength={2000} />
      </Form.Item>
      <Form.Item name={['config', 'conversation', 'input_placeholder']} label="输入框提示">
        <Input placeholder="例如：请输入你的问题" maxLength={200} />
      </Form.Item>
      <Form.Item
        name={['config', 'conversation', 'common_questions_enabled']}
        label="展示常见问题"
        valuePropName="checked"
      >
        <Switch checkedChildren="开" unCheckedChildren="关" />
      </Form.Item>

      <Form.List name={['config', 'conversation', 'faqs']}>
        {(fields, { add, remove }) => (
          <div className="faq-list">
            {fields.map(({ key, name }) => (
              <Row key={key} gutter={12} align="top" className="faq-item">
                <Col xs={24} md={9}>
                  <Form.Item
                    name={[name, 'question']}
                    label="问题"
                    rules={[{ required: true, message: '请输入问题' }]}
                  >
                    <Input placeholder="常见问题" maxLength={500} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={13}>
                  <Form.Item name={[name, 'answer']} label="回答">
                    <Input.TextArea rows={2} placeholder="对应回答" maxLength={2000} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={2}>
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    className="faq-item__remove"
                    onClick={() => remove(name)}
                  />
                </Col>
              </Row>
            ))}
            <Button
              type="dashed"
              block
              icon={<PlusOutlined />}
              onClick={() => add({ question: '', answer: '' })}
            >
              添加常见问题
            </Button>
          </div>
        )}
      </Form.List>
    </Card>
  )
}
