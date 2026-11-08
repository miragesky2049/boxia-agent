import { CheckOutlined, DownOutlined, RightOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { PlanTask, ReflectNote } from '../types'

// 0074 PRD F4：深度模式进展卡（plan 任务清单 + 每轮 reflect 结论），默认收起减少刷屏
export function PlanProgressCard({ tasks, reflects }: { tasks: PlanTask[]; reflects: ReflectNote[] }) {
  const [expanded, setExpanded] = useState(false)
  if (tasks.length === 0 && reflects.length === 0) return null
  const last = reflects[reflects.length - 1]
  const summary = last
    ? `已评审 ${reflects.length} 轮 · ${last.done ? '通过' : '待改进'}`
    : `任务规划（${tasks.length} 项）`

  return (
    <div className={`lc-plan ${last?.done ? 'is-done' : ''}`}>
      <button type="button" className="lc-plan__header" onClick={() => setExpanded((prev) => !prev)}>
        {last?.done ? (
          <CheckOutlined className="lc-trace__icon is-done" />
        ) : (
          <span className="lc-spinner" aria-hidden />
        )}
        <span className="lc-trace__label">{summary}</span>
        <span className="lc-trace__chevron" aria-hidden>
          {expanded ? <DownOutlined /> : <RightOutlined />}
        </span>
      </button>
      {expanded && (
        <div className="lc-plan__body">
          {tasks.length > 0 && (
            <div className="lc-trace__block">
              <span className="lc-trace__block-label">任务清单</span>
              <ol className="lc-plan__tasks">
                {tasks.map((task, index) => (
                  <li key={task.id ?? index}>
                    {task.goal}
                    {task.acceptance ? <span className="lc-plan__acceptance">（验收：{task.acceptance}）</span> : null}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {reflects.map((note) => (
            <div className="lc-trace__block" key={note.round}>
              <span className="lc-trace__block-label">第 {note.round} 轮评审</span>
              <div className="lc-plan__reflect">
                {note.done ? '评审通过，可输出最终回答' : note.critique || '尚未达标'}
                {note.suggestion ? `；改进建议：${note.suggestion}` : ''}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
