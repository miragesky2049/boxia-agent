import { Space, Tag } from 'antd'
import { promptsApi } from '../api/resources'
import type { PromptPayload, PromptResource } from '../api/types'
import ResourceListPage from '../components/ResourceListPage'
import type { FormField, ListColumn } from '../components/ResourceListPage'

const columns: ListColumn<PromptResource>[] = [
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

const fields: FormField[] = [
  { name: 'name', label: '提示词名称', required: true, placeholder: '例如：陪练开场白' },
  { name: 'description', label: '描述', type: 'textarea', rows: 2 },
  {
    name: 'content',
    label: '提示词内容',
    type: 'textarea',
    rows: 6,
    placeholder: '支持使用 {{变量名}} 占位',
  },
  { name: 'category', label: '分类', placeholder: '例如：system / user' },
  { name: 'variables', label: '变量', type: 'tags', placeholder: '输入变量名后回车' },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const defaults: PromptPayload = {
  name: '',
  description: '',
  is_enabled: true,
  content: '',
  variables: [],
  category: '',
}

export default function PromptsPage() {
  return (
    <ResourceListPage<PromptResource, PromptPayload>
      title="提示词管理"
      description="沉淀可复用的提示词模板与变量。"
      api={promptsApi}
      columns={columns}
      fields={fields}
      defaults={defaults}
      createText="新建提示词"
    />
  )
}
