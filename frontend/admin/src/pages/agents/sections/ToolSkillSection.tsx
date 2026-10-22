import { Card, Form, Select } from 'antd'
import type { Skill, Tool } from '../../../api/types'

interface Props {
  tools: Tool[]
  skills: Skill[]
}

export default function ToolSkillSection({ tools, skills }: Props) {
  return (
    <Card id="section-tools" title="工具与技能" className="config-card">
      <Form.Item
        name="tool_ids"
        label="可用工具"
        extra={tools.length ? '智能体可调用的外部工具' : '暂无工具，请先在工具管理中创建'}
      >
        <Select
          mode="multiple"
          placeholder="选择工具"
          optionFilterProp="label"
          options={tools.map((tool) => ({
            label: `${tool.name}（${tool.type}）`,
            value: tool.id,
          }))}
        />
      </Form.Item>
      <Form.Item
        name="skill_ids"
        label="关联技能"
        extra={skills.length ? '智能体可调用的技能' : '暂无技能，请先在技能管理中创建'}
      >
        <Select
          mode="multiple"
          placeholder="选择技能"
          optionFilterProp="label"
          options={skills.map((skill) => ({ label: skill.name, value: skill.id }))}
        />
      </Form.Item>
    </Card>
  )
}
