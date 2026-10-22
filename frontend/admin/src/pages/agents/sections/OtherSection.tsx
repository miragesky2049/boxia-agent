import { Card, Col, Form, Input, InputNumber, Row, Select, Switch } from 'antd'

const SWITCH_FIELDS = [
  { key: 'deep_thinking', label: '深度思考' },
  { key: 'show_reasoning', label: '展示推理过程' },
  { key: 'web_search', label: '联网搜索' },
  { key: 'create_task', label: '创建任务' },
  { key: 'history_task', label: '历史任务' },
  { key: 'scheduled_task', label: '定时任务' },
  { key: 'artifacts', label: '产物（Artifacts）' },
  { key: 'upload_attachment', label: '上传附件' },
  { key: 'task_list', label: '任务列表' },
]

export default function OtherSection() {
  return (
    <Card id="section-other" title="其他设置" className="config-card">
      <Row gutter={20}>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'other', 'system_prompt_template']} label="系统提示词模板">
            <Input placeholder="default" />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name={['config', 'other', 'max_turns']} label="最大对话轮数">
            <InputNumber min={1} max={500} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={20}>
        {SWITCH_FIELDS.map((item) => (
          <Col xs={12} md={8} key={item.key}>
            <Form.Item
              name={['config', 'other', item.key]}
              label={item.label}
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          </Col>
        ))}
      </Row>

      <Row gutter={20}>
        <Col xs={24} md={16}>
          <Form.Item name={['config', 'other', 'upload_file_types']} label="允许上传的文件类型">
            <Select mode="tags" placeholder="输入扩展名后回车，例如 pdf" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name={['config', 'other', 'upload_max_size_mb']} label="附件大小上限（MB）">
            <InputNumber min={1} max={100} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
    </Card>
  )
}
