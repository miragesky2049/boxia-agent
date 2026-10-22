import { Tag } from 'antd'
import { toolsApi } from '../api/resources'
import type { Tool, ToolPayload } from '../api/types'
import ResourceListPage from '../components/ResourceListPage'
import type { FormField, ListColumn } from '../components/ResourceListPage'

const columns: ListColumn<Tool>[] = [
  {
    title: '类型',
    key: 'type',
    width: 110,
    render: (record) => <Tag color="blue">{record.type}</Tag>,
  },
]

const fields: FormField[] = [
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
  {
    name: 'config',
    label: '配置（JSON）',
    type: 'json',
    rows: 6,
    placeholder: '{"url": "https://..."}',
  },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const defaults: ToolPayload = {
  name: '',
  description: '',
  is_enabled: true,
  type: 'http',
  config: {},
}

export default function ToolsPage() {
  return (
    <ResourceListPage<Tool, ToolPayload>
      title="工具管理"
      description="配置智能体可调用的外部工具与接口。"
      api={toolsApi}
      columns={columns}
      fields={fields}
      defaults={defaults}
      createText="新建工具"
    />
  )
}
