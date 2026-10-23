import { Button } from 'antd'
import { useRef, useState } from 'react'
import { skillsApi } from '../api/resources'
import type { Skill, SkillPayload } from '../api/types'
import ResourceListPage from '../components/ResourceListPage'
import type { FormField, ListColumn, RowActionHelpers } from '../components/ResourceListPage'
import SkillPackageDrawer from './skills/SkillPackageDrawer'

const columns: ListColumn<Skill>[] = [
  {
    title: '技能内容',
    key: 'content',
    render: (record) => <span className="cell-ellipsis">{record.content || '-'}</span>,
  },
]

const fields: FormField[] = [
  { name: 'name', label: '技能名称', required: true, placeholder: '例如：剧本生成' },
  {
    name: 'description',
    label: '描述',
    type: 'textarea',
    rows: 2,
    placeholder: '一句话说明技能用途',
  },
  {
    name: 'content',
    label: '技能内容',
    type: 'textarea',
    rows: 6,
    placeholder: '描述技能的执行逻辑或指令',
  },
  { name: 'is_enabled', label: '是否启用', type: 'switch' },
]

const defaults: SkillPayload = {
  name: '',
  description: '',
  is_enabled: true,
  content: '',
  config: {},
}

export default function SkillsPage() {
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
        description="维护智能体可调用的技能，定义执行逻辑与指令。"
        api={skillsApi}
        columns={columns}
        fields={fields}
        defaults={defaults}
        createText="新建技能"
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
