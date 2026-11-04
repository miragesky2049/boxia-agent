import {
  CalendarOutlined,
  CodeOutlined,
  DatabaseOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'
import type { ChatAgent } from '../types'

export interface Suggestion {
  icon: 'code' | 'calendar' | 'database' | 'bolt'
  title: string
  description: string
}

interface WelcomeHeroProps {
  agent: ChatAgent
  suggestions: readonly Suggestion[]
  onPick?: (title: string) => void
}

const ICONS: Record<Suggestion['icon'], ReactNode> = {
  code: <CodeOutlined />,
  calendar: <CalendarOutlined />,
  database: <DatabaseOutlined />,
  bolt: <ThunderboltOutlined />,
}

export function WelcomeHero({ agent, suggestions, onPick }: WelcomeHeroProps) {
  return (
    <div className="lc-welcome">
      <div className="lc-welcome__avatar" aria-hidden>
        {agent.avatarText}
      </div>
      <h1 className="lc-welcome__title">你好，今天想聊点什么？</h1>
      <p className="lc-welcome__subtitle">
        我是{agent.name}，可以直接向我提问，或从下面的建议开始。
      </p>

      <div className="lc-suggestions">
        {suggestions.map((item) => (
          <button
            type="button"
            key={item.title}
            className="lc-suggestion"
            onClick={() => onPick?.(item.title)}
          >
            <span className="lc-suggestion__icon" aria-hidden>
              {ICONS[item.icon]}
            </span>
            <span className="lc-suggestion__title">{item.title}</span>
            <span className="lc-suggestion__desc">{item.description}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
