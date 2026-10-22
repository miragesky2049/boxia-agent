import { Tag } from 'antd'
import { componentsApi } from '../api/resources'
import type { ComponentPayload, ComponentResource } from '../api/types'
import ResourceListPage from '../components/ResourceListPage'
import type { FormField, ListColumn } from '../components/ResourceListPage'

const columns: ListColumn<ComponentResource>[] = [
  {
    title: '类型',
    key: 'type',
    width: 110,
    render: (record) => <Tag color="purple">{record.type}</Tag>,
  },
]

const fields: FormField[] = [
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
  {
    name: 'config',
    label: '配置（JSON）',
    type: 'json',
    rows: 6,
    placeholder: '{"layout": "grid"}',
  },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const defaults: ComponentPayload = {
  name: '',
  description: '',
  is_enabled: true,
  type: 'card',
  config: {},
}

export default function ComponentsPage() {
  return (
    <ResourceListPage<ComponentResource, ComponentPayload>
      title="组件管理"
      description="管理智能体对话页可使用的前端组件。"
      api={componentsApi}
      columns={columns}
      fields={fields}
      defaults={defaults}
      createText="新建组件"
    />
  )
}
