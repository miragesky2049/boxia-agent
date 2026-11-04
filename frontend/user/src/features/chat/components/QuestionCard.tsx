import { CheckOutlined } from '@ant-design/icons'
import { useState } from 'react'
import type { QuestionSpec } from '../types'

interface QuestionCardProps {
  question: QuestionSpec
  onSubmit?: (answer: string) => void
}

export function QuestionCard({ question, onSubmit }: QuestionCardProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [custom, setCustom] = useState('')
  const [submitted, setSubmitted] = useState<string | null>(
    question.submitted ? '已提交' : null,
  )

  const answer = custom.trim() || selected || ''

  const handleSubmit = () => {
    if (!answer || submitted) return
    onSubmit?.(answer)
    setSubmitted(answer)
  }

  if (submitted) {
    return (
      <div className="lc-question is-submitted">
        <span className="lc-question__submitted-icon">
          <CheckOutlined />
        </span>
        <span>已提交：{submitted === '已提交' ? answer || '已回答' : submitted}</span>
      </div>
    )
  }

  return (
    <div className="lc-question">
      <div className="lc-question__title">需要你的确认</div>
      <div className="lc-question__text">{question.text}</div>

      {question.options && question.options.length > 0 && (
        <div className="lc-question__options">
          {question.options.map((option) => (
            <button
              type="button"
              key={option}
              className={`lc-option${selected === option ? ' is-selected' : ''}`}
              onClick={() => {
                setSelected(option)
                setCustom('')
              }}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      <input
        className="lc-question__input"
        value={custom}
        placeholder="也可以直接输入你的回答…"
        onChange={(event) => {
          setCustom(event.target.value)
          if (event.target.value) setSelected(null)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') handleSubmit()
        }}
      />

      <div className="lc-question__footer">
        <button
          type="button"
          className="lc-btn lc-btn--primary"
          disabled={!answer}
          onClick={handleSubmit}
        >
          提交并继续
        </button>
      </div>
    </div>
  )
}
