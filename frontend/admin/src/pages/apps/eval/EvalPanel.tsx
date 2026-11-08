import { useState } from 'react'
import { Tabs } from 'antd'
import DatasetsPanel from './DatasetsPanel'
import EvaluatorsPanel from './EvaluatorsPanel'
import RunsPanel from './RunsPanel'
import QualityPanel from './QualityPanel'

interface EvalPanelProps {
  applicationId: string
}

/**
 * 应用详情「评测」页签（M4-d T-d6）：数据集 / 评估器 / 评测运行 / 质量四块。
 * Tabs 用受控 activeKey（RoleDetailPage 先例，jsdom 下非受控切换存在内容滞后）。
 */
export default function EvalPanel({ applicationId }: EvalPanelProps) {
  const [activeKey, setActiveKey] = useState('datasets')
  return (
    <Tabs
      activeKey={activeKey}
      onChange={setActiveKey}
      items={[
        {
          key: 'datasets',
          label: '数据集',
          children: <DatasetsPanel applicationId={applicationId} />,
        },
        {
          key: 'evaluators',
          label: '评估器',
          children: <EvaluatorsPanel />,
        },
        {
          key: 'runs',
          label: '评测运行',
          children: <RunsPanel applicationId={applicationId} />,
        },
        {
          key: 'quality',
          label: '质量',
          children: <QualityPanel applicationId={applicationId} />,
        },
      ]}
    />
  )
}
