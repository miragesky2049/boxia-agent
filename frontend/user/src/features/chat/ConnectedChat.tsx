import { Spin } from 'antd'
import { useEffect, useState } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { getAgent } from '../../api/agents'
import type { UserAgentDetail } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { getTenantCode } from '../../tenant/scope'
import { ChatWorkbench } from './ChatWorkbench'
import type { Suggestion } from './components/WelcomeHero'
import { useChatSession } from './hooks/useChatSession'
import type { ChatAgent } from './types'

const SUGGESTIONS: Suggestion[] = [
  {
    icon: 'bolt',
    title: '你好，请介绍一下你能帮我做什么',
    description: '快速了解这个智能体的能力边界',
  },
  {
    icon: 'code',
    title: '帮我快速梳理当前任务的关键点',
    description: '把复杂问题拆成可执行的步骤',
  },
  {
    icon: 'calendar',
    title: '演示一次你的核心能力',
    description: '用一个小例子看看实际效果',
  },
]

export function ConnectedChat() {
  const { agentId } = useParams<{ agentId: string }>()
  const { user } = useAuth()
  const [agent, setAgent] = useState<UserAgentDetail | null>(null)
  const [agentLoading, setAgentLoading] = useState(true)
  const [agentError, setAgentError] = useState<string | null>(null)

  const session = useChatSession({ agentId, flowType: agent?.flow_type })

  // 0074 F3.4：智能体配置面的开场白与推荐问题（详情卡片 config 新键）
  const agentConfig = (agent?.config ?? {}) as {
    opening_remarks?: string
    suggested_questions?: string[]
    vision_enabled?: boolean
  }
  const suggestions: Suggestion[] = agentConfig.suggested_questions?.length
    ? agentConfig.suggested_questions.map((question) => ({
        icon: 'bolt',
        title: question,
        description: '点击直接发送',
      }))
    : SUGGESTIONS

  useEffect(() => {
    if (!agentId) {
      setAgentError('智能体地址不正确')
      setAgentLoading(false)
      return
    }
    let active = true
    setAgentLoading(true)
    setAgentError(null)
    getAgent(agentId)
      .then((data) => {
        if (active) setAgent(data)
      })
      .catch((err: unknown) => {
        if (active) setAgentError(err instanceof Error ? err.message : '加载智能体失败')
      })
      .finally(() => {
        if (active) setAgentLoading(false)
      })
    return () => {
      active = false
    }
  }, [agentId])

  if (agentLoading) {
    return (
      <div className="lc-page lc-page--center">
        <Spin size="large" />
      </div>
    )
  }

  if (agentError || !agent) {
    return (
      <div className="lc-page lc-page--center">
        <div className="lc-error-state">
          <div className="lc-error-state__title">无法打开智能体</div>
          <p className="lc-error-state__desc">{agentError ?? '智能体不存在或未授权'}</p>
          <Link to="/agents">
            <button type="button" className="lc-btn lc-btn--primary">
              返回应用列表
            </button>
          </Link>
        </div>
      </div>
    )
  }

  if (agent.flow_type === 'workflow') {
    return <Navigate to={`/agents/${agent.id}/workflow`} replace />
  }

  const chatAgent: ChatAgent = {
    id: agent.id,
    name: agent.name,
    avatarText: agent.name.trim().slice(0, 1) || 'AI',
  }

  return (
    <ChatWorkbench
      agent={chatAgent}
      conversations={session.conversationItems}
      conversationsLoading={session.conversationsLoading}
      activeConversationId={session.conversationId}
      messages={session.messages}
      suggestions={suggestions}
      openingRemarks={agentConfig.opening_remarks || undefined}
      streaming={session.streaming}
      userName={user?.display_name || user?.username || '当前用户'}
      tenantCode={getTenantCode()}
      imagesEnabled={agent.flow_type === 'agent' && Boolean(agentConfig.vision_enabled)}
      // M4 PRD F16.6：仅智能体应用有长期记忆管理入口（chatflow 无长期记忆）
      memoriesEnabled={agent.flow_type === 'agent'}
      onSend={(text, images) => {
        void session.send(text, images)
      }}
      onStop={session.stop}
      onNewChat={session.newConversation}
      onSelectConversation={(id) => {
        void session.selectConversation(id)
      }}
      onRetry={
        agent.flow_type === 'chatflow'
          ? undefined
          : () => {
              void session.retry()
            }
      }
      onAnswer={
        session.pendingQuestion
          ? (answer) => {
              void session.send(answer)
            }
          : undefined
      }
      onApprovalDecision={(approved, comment, approval) => {
        void session.resolveApproval(approved, comment, approval)
      }}
      // M4 PRD F14.9：接管中（发言权在专家）时 Composer 提供手动归位
      handbackVisible={Boolean(session.activeHandoff)}
      onHandback={() => {
        void session.handback()
      }}
    />
  )
}
