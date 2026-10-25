import { Button, Space, Tabs, Tag } from 'antd'
import { useRef, useState } from 'react'
import { componentsApi, promptsApi, skillsApi, toolsApi } from '../../api/resources'
import type {
  ComponentPayload,
  ComponentResource,
  PromptPayload,
  PromptResource,
  Skill,
  SkillPayload,
  Tool,
  ToolPayload,
} from '../../api/types'
import ResourceListPage from '../../components/ResourceListPage'
import type { FormField, ListColumn, RowActionHelpers } from '../../components/ResourceListPage'
import SkillPackageDrawer from '../skills/SkillPackageDrawer'

const SKILL_COLUMNS: ListColumn<Skill>[] = [
  {
    title: '技能内容',
    key: 'content',
    render: (record) => <span className="cell-ellipsis">{record.content || '-'}</span>,
  },
]

const SKILL_FIELDS: FormField[] = [
  { name: 'name', label: '技能名称', required: true, placeholder: '例如：剧本生成' },
  { name: 'description', label: '描述', type: 'textarea', rows: 2 },
  { name: 'content', label: '技能内容', type: 'textarea', rows: 6 },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const SKILL_DEFAULTS: SkillPayload = {
  name: '',
  description: '',
  is_enabled: true,
  content: '',
  config: {},
}

const TOOL_COLUMNS: ListColumn<Tool>[] = [
  {
    title: '类型',
    key: 'type',
    width: 110,
    render: (record) => <Tag color="blue">{record.type}</Tag>,
  },
]

const TOOL_FIELDS: FormField[] = [
  { name: 'name', label: '工具名称', required: true, placeholder: '例如：HTTP 查询' },
  { name: 'description', label: '描述', type: 'textarea', rows: 2 },
  {
    name: 'type',
    label: '工具类型',
    type: 'select',
    options: [
      { label: 'HTTP 接口', value: 'http' },
      { label: 'MCP', value: 'mcp' },
      { label: '函数', value: 'function' },
      { label: '代码', value: 'code' },
    ],
  },
  { name: 'config', label: '配置（JSON）', type: 'json', rows: 6 },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const TOOL_DEFAULTS: ToolPayload = {
  name: '',
  description: '',
  is_enabled: true,
  type: 'http',
  config: {},
}

const COMPONENT_COLUMNS: ListColumn<ComponentResource>[] = [
  {
    title: '类型',
    key: 'type',
    width: 110,
    render: (record) => <Tag color="purple">{record.type}</Tag>,
  },
]

const COMPONENT_FIELDS: FormField[] = [
  { name: 'name', label: '组件名称', required: true, placeholder: '例如：推荐卡片' },
  { name: 'description', label: '描述', type: 'textarea', rows: 2 },
  {
    name: 'type',
    label: '组件类型',
    type: 'select',
    options: [
      { label: '卡片', value: 'card' },
      { label: '列表', value: 'list' },
      { label: '表单', value: 'form' },
      { label: '表格', value: 'table' },
    ],
  },
  { name: 'config', label: '配置（JSON）', type: 'json', rows: 6 },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const COMPONENT_DEFAULTS: ComponentPayload = {
  name: '',
  description: '',
  is_enabled: true,
  type: 'card',
  config: {},
}

const PROMPT_COLUMNS: ListColumn<PromptResource>[] = [
  {
    title: '分类',
    key: 'category',
    width: 110,
    render: (record) => (record.category ? <Tag>{record.category}</Tag> : '-'),
  },
  {
    title: '变量',
    key: 'variables',
    width: 200,
    render: (record) =>
      record.variables.length ? (
        <Space size={4} wrap>
          {record.variables.map((item) => (
            <Tag key={item} color="geekblue">
              {item}
            </Tag>
          ))}
        </Space>
      ) : (
        '-'
      ),
  },
  {
    title: '内容',
    key: 'content',
    render: (record) => <span className="cell-ellipsis">{record.content || '-'}</span>,
  },
]

const PROMPT_FIELDS: FormField[] = [
  { name: 'name', label: '提示词名称', required: true, placeholder: '例如：陪练开场白' },
  { name: 'description', label: '描述', type: 'textarea', rows: 2 },
  { name: 'content', label: '提示词内容', type: 'textarea', rows: 6 },
  { name: 'category', label: '分类', placeholder: '例如：system / user' },
  { name: 'variables', label: '变量', type: 'tags', placeholder: '输入变量名后回车' },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const PROMPT_DEFAULTS: PromptPayload = {
  name: '',
  description: '',
  is_enabled: true,
  content: '',
  variables: [],
  category: '',
}

function SkillList({ agentId }: { agentId: number }) {
  const [packageSkill, setPackageSkill] = useState<Skill | null>(null)
  const reloadRef = useRef<() => Promise<void>>(async () => undefined)

  const openPackage = (record: Skill, helpers: RowActionHelpers) => {
    reloadRef.current = helpers.reload
    setPackageSkill(record)
  }

  return (
    <>
      <ResourceListPage<Skill, SkillPayload>
        title="技能管理"
        description="维护智能体可调用的技能，跨智能体复用请使用克隆。"
        api={skillsApi}
        columns={SKILL_COLUMNS}
        fields={SKILL_FIELDS}
        defaults={SKILL_DEFAULTS}
        createText="新建技能"
        agentId={agentId}
        resourceType="skill"
        enableClone
        extraActions={(record, helpers) => (
          <Button type="link" size="small" onClick={() => openPackage(record, helpers)}>
            技能包
          </Button>
        )}
      />
      <SkillPackageDrawer
        skill={packageSkill}
        open={packageSkill !== null}
        onClose={() => setPackageSkill(null)}
        onChanged={() => reloadRef.current()}
      />
    </>
  )
}

export default function AgentResourcesTab({ agentId }: { agentId?: number }) {
  if (agentId === undefined) {
    return <div className="page-card">请先保存智能体，再维护技能、工具、组件与提示词。</div>
  }

  return (
    <Tabs
      items={[
        { key: 'skills', label: '技能', children: <SkillList agentId={agentId} /> },
        {
          key: 'tools',
          label: '工具',
          children: (
            <ResourceListPage<Tool, ToolPayload>
              title="工具管理"
              description="配置智能体可调用的外部工具与接口。"
              api={toolsApi}
              columns={TOOL_COLUMNS}
              fields={TOOL_FIELDS}
              defaults={TOOL_DEFAULTS}
              createText="新建工具"
              agentId={agentId}
              resourceType="tool"
              enableClone
            />
          ),
        },
        {
          key: 'components',
          label: '组件',
          children: (
            <ResourceListPage<ComponentResource, ComponentPayload>
              title="组件管理"
              description="管理智能体对话页可使用的前端组件。"
              api={componentsApi}
              columns={COMPONENT_COLUMNS}
              fields={COMPONENT_FIELDS}
              defaults={COMPONENT_DEFAULTS}
              createText="新建组件"
              agentId={agentId}
              resourceType="component"
              enableClone
            />
          ),
        },
        {
          key: 'prompts',
          label: '提示词',
          children: (
            <ResourceListPage<PromptResource, PromptPayload>
              title="提示词管理"
              description="沉淀智能体专属的提示词模板与变量。"
              api={promptsApi}
              columns={PROMPT_COLUMNS}
              fields={PROMPT_FIELDS}
              defaults={PROMPT_DEFAULTS}
              createText="新建提示词"
              agentId={agentId}
              resourceType="prompt"
              enableClone
            />
          ),
        },
      ]}
    />
  )
}
