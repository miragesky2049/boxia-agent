import { Card, Col, Form, Input, Row, Switch } from 'antd'

export default function BasicSection() {
  return (
    <Card id="section-basic" title="基础信息" className="config-card">
      <Row gutter={20}>
        <Col xs={24} md={12}>
          <Form.Item
            name="name"
            label="智能体名称"
            rules={[{ required: true, message: '请输入智能体名称' }]}
          >
            <Input placeholder="例如：陪练剧本生成智能体" maxLength={100} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="avatar_url" label="头像地址">
            <Input placeholder="https://example.com/avatar.png" maxLength={500} />
          </Form.Item>
        </Col>
        <Col xs={24}>
          <Form.Item name="description" label="简介">
            <Input.TextArea
              rows={2}
              maxLength={5000}
              placeholder="简要说明智能体的能力与适用场景"
            />
          </Form.Item>
        </Col>
        <Col xs={24}>
          <Form.Item name="is_enabled" label="启用状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Col>
      </Row>
    </Card>
  )
}
