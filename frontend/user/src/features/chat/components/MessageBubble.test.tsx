import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MessageBubble } from './MessageBubble'
import type { ChatAgent } from '../types'

const agent: ChatAgent = { id: 'a1', name: '主助手', avatarText: '主' }

// M4 PRD F14.10：发言权通告气泡与应答 agent 徽标的渲染出口
describe('MessageBubble 接管发言权展示', () => {
  it('接管通告行渲染为居中通告气泡，不带助手头像与正文区', () => {
    const { container } = render(
      <MessageBubble
        agent={agent}
        message={{
          id: 'n1',
          role: 'assistant',
          content: '',
          handoffNotice: '会话已移交给专家「天气专家」，后续对话由其应答。',
        }}
      />,
    )
    expect(screen.getByText(/天气专家/)).toBeInTheDocument()
    expect(container.querySelector('.lc-msg')).toBeNull()
    expect(container.querySelector('.lc-handoff-notice')).not.toBeNull()
  })

  it('接管轮助手气泡展示应答专家徽标，归属轮助手不带徽标', () => {
    const { rerender } = render(
      <MessageBubble
        agent={agent}
        message={{ id: 'm1', role: 'assistant', content: '明天晴，20 度。', answeredBy: '天气专家' }}
      />,
    )
    expect(screen.getByText('由「天气专家」应答')).toBeInTheDocument()

    rerender(
      <MessageBubble agent={agent} message={{ id: 'm2', role: 'assistant', content: '你好' }} />,
    )
    expect(screen.queryByText(/应答/)).toBeNull()
  })
})
