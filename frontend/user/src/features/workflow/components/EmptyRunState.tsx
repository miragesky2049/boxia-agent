import { NodeIndexOutlined } from '@ant-design/icons'

/** 未运行时的空态占位。 */
export default function EmptyRunState() {
  return (
    <div className="wf-empty">
      <div className="wf-empty__icon" aria-hidden="true">
        <NodeIndexOutlined />
      </div>
      <div className="wf-empty__title">开始一次运行</div>
      <p className="wf-empty__desc">
        在左侧填写入参并点击「开始运行」，这里会实时展示每个节点的执行轨迹与最终结果。
      </p>
    </div>
  )
}
