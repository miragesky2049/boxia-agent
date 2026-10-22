import { Card, Col, Form, Row, Select, Switch } from 'antd'

export default function ChannelSection() {
  return (
    <Card id="section-channel" title="发布渠道" className="config-card">
      <Row gutter={20}>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'channel', 'type']} label="渠道类型">
            <Select
              options={[
                { label: '网页对话', value: 'web' },
                { label: '移动应用', value: 'app' },
                { label: '开放 API', value: 'api' },
              ]}
            />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item
            name={['config', 'channel', 'enabled']}
            label="渠道启用"
            valuePropName="checked"
          >
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </Col>
      </Row>
    </Card>
  )
}
