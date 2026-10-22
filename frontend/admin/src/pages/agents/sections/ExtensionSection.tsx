import { Card, Col, Form, Row, Select } from 'antd'
import type { ComponentResource } from '../../../api/types'

interface Props {
  components: ComponentResource[]
}

const SLOTS = [
  { key: 'chat_header', label: '对话页顶部' },
  { key: 'chat_footer', label: '对话页底部' },
  { key: 'sidebar_top', label: '侧边栏顶部' },
  { key: 'sidebar_bottom', label: '侧边栏底部' },
]

export default function ExtensionSection({ components }: Props) {
  return (
    <Card id="section-extension" title="扩展组件" className="config-card">
      <p className="config-card__tip">将组件挂载到对话页的指定位置，未选择则使用默认布局。</p>
      <Row gutter={20}>
        {SLOTS.map((slot) => (
          <Col xs={24} md={12} key={slot.key}>
            <Form.Item name={['config', 'extensions', slot.key]} label={slot.label}>
              <Select
                allowClear
                placeholder="不挂载组件"
                optionFilterProp="label"
                options={components.map((component) => ({
                  label: `${component.name}（${component.type}）`,
                  value: component.id,
                }))}
              />
            </Form.Item>
          </Col>
        ))}
      </Row>
    </Card>
  )
}
