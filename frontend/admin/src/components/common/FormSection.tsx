import type { ReactNode } from 'react'
import './form-section.css'

interface FormSectionProps {
  title: ReactNode
  description?: ReactNode
  extra?: ReactNode
  children: ReactNode
}

/**
 * 表单分区卡片：浅灰底 + 左侧品牌色竖条 + 标题下细分隔线。
 * 统一替代 antd <Divider orientation="left" dashed> 的视觉弱分区。
 */
export function FormSection({ title, description, extra, children }: FormSectionProps) {
  return (
    <section className="form-section">
      <header className="form-section__header">
        <div className="form-section__heading">
          <h4 className="form-section__title">{title}</h4>
          {description ? <p className="form-section__desc">{description}</p> : null}
        </div>
        {extra ? <div className="form-section__extra">{extra}</div> : null}
      </header>
      <div className="form-section__body">{children}</div>
    </section>
  )
}
