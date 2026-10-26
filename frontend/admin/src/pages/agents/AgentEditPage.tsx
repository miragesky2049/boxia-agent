import { ArrowLeftOutlined } from '@ant-design/icons'
import { Anchor, App, Button, Form, Space, Spin, Tabs, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { createAgent, getAgent, updateAgent } from '../../api/agents'
import { departmentsApi } from '../../api/department'
import { componentsApi, skillsApi, toolsApi } from '../../api/resources'
import type { AgentConfig, AgentPayload, ComponentResource, Skill, Tool } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { useTenant } from '../../tenant/TenantContext'
import type { DepartmentTreeNode } from '../../utils/departmentTree'
import { buildDepartmentTreeData } from '../../utils/departmentTree'
import AgentResourcesTab from './AgentResourcesTab'
import AgentTenantsTab from './AgentTenantsTab'
import AgentVisibilityTab from './AgentVisibilityTab'
import BasicSection from './sections/BasicSection'
import ChannelSection from './sections/ChannelSection'
import ConversationSection from './sections/ConversationSection'
import ExtensionSection from './sections/ExtensionSection'
import KnowledgeSection from './sections/KnowledgeSection'
import MemorySection from './sections/MemorySection'
import ModelSection from './sections/ModelSection'
import OtherSection from './sections/OtherSection'
import PromptSection from './sections/PromptSection'
import ToolSkillSection from './sections/ToolSkillSection'
import './AgentEditPage.css'

const DEFAULT_CONFIG: AgentConfig = {
  model: {
    model: 'glm-5',
    temperature: 0.2,
    max_output_tokens: 8192,
    reasoning_effort: 'medium',
    context_window: 65536,
    max_thinking_tokens: 2000,
  },
  prompt: {
    role_setting: '',
    persona: '',
    user_prompt: '',
    memory_count: 20,
    memory_model: 'glm-5',
  },
  memory: {
    enabled: false,
    task_memory_prompt: '',
    long_term_enabled: false,
    long_term_prompt: '',
  },
  conversation: {
    welcome: '',
    fallback: '',
    input_placeholder: '',
    common_questions_enabled: false,
    faqs: [],
  },
  channel: { type: 'web', enabled: true },
  knowledge: { enabled: false, dataset_ids: [] },
  other: {
    system_prompt_template: 'default',
    max_turns: 30,
    deep_thinking: true,
    show_reasoning: true,
    web_search: false,
    create_task: true,
    history_task: true,
    scheduled_task: false,
    artifacts: false,
    upload_attachment: true,
    upload_file_types: ['txt', 'md', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'ppt', 'pptx'],
    upload_max_size_mb: 10,
    task_list: false,
  },
  extensions: {},
}

interface AgentFormValues {
  name: string
  avatar_url?: string
  description?: string
  is_enabled?: boolean
  config: AgentConfig
  tool_ids?: string[]
  skill_ids?: string[]
  department_id?: string | null
}

const ANCHOR_ITEMS = [
  { key: 'basic', href: '#section-basic', title: '基础信息' },
  { key: 'model', href: '#section-model', title: '模型配置' },
  { key: 'prompt', href: '#section-prompt', title: '角色与提示词' },
  { key: 'memory', href: '#section-memory', title: '记忆配置' },
  { key: 'conversation', href: '#section-conversation', title: '对话体验' },
  { key: 'channel', href: '#section-channel', title: '发布渠道' },
  { key: 'tools', href: '#section-tools', title: '工具与技能' },
  { key: 'knowledge', href: '#section-knowledge', title: '知识库' },
  { key: 'other', href: '#section-other', title: '其他设置' },
  { key: 'extension', href: '#section-extension', title: '扩展组件' },
]

export default function AgentEditPage() {
  const { id } = useParams<{ id: string }>()
  const agentId = id
  const isEdit = Boolean(agentId)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = hasPermission('button:agent:create')
  const canUpdate = hasPermission('button:agent:update')
  const { isPlatform } = useTenant()
  const [form] = Form.useForm<AgentFormValues>()
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving] = useState(false)
  const [platformResource, setPlatformResource] = useState(false)
  const canSubmit = isEdit ? canUpdate : canCreate
  const readonly = !canSubmit || (!isPlatform && platformResource)
  const [tools, setTools] = useState<Tool[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [components, setComponents] = useState<ComponentResource[]>([])
  const [deptTreeData, setDeptTreeData] = useState<DepartmentTreeNode[]>([])

  useEffect(() => {
    let active = true

    async function loadOptions() {
      try {
        const [toolResult, skillResult, componentResult, departmentResult] = await Promise.all([
          toolsApi.list({ page: 1, page_size: 100 }),
          skillsApi.list({ page: 1, page_size: 100 }),
          componentsApi.list({ page: 1, page_size: 100 }),
          isPlatform ? Promise.resolve([]) : departmentsApi.tree().catch(() => []),
        ])
        if (!active) return
        setTools(toolResult.items)
        setSkills(skillResult.items)
        setComponents(componentResult.items)
        setDeptTreeData(buildDepartmentTreeData(departmentResult))
      } catch (error) {
        message.error(error instanceof Error ? error.message : '加载选项失败')
      }
    }

    async function loadAgent() {
      if (agentId === undefined) {
        form.setFieldsValue({
          name: '',
          avatar_url: '',
          description: '',
          is_enabled: true,
          config: structuredClone(DEFAULT_CONFIG),
          tool_ids: [],
          skill_ids: [],
          department_id: null,
        })
        return
      }
      try {
        const agent = await getAgent(agentId)
        if (!active) return
        setPlatformResource(agent.is_platform)
        form.setFieldsValue({
          name: agent.name,
          avatar_url: agent.avatar_url,
          description: agent.description,
          is_enabled: agent.is_enabled,
          config: agent.config,
          tool_ids: agent.tool_ids,
          skill_ids: agent.skill_ids,
          department_id: agent.department_id ?? null,
        })
      } catch (error) {
        message.error(error instanceof Error ? error.message : '加载智能体失败')
        navigate('/agents', { replace: true })
      } finally {
        if (active) setLoading(false)
      }
    }

    void loadOptions()
    void loadAgent()
    return () => {
      active = false
    }
  }, [agentId, form, isEdit, isPlatform, navigate, message])

  const handleFinish = async (values: AgentFormValues) => {
    const payload: AgentPayload = {
      name: values.name.trim(),
      avatar_url: values.avatar_url ?? '',
      description: values.description ?? '',
      is_enabled: values.is_enabled ?? true,
      config: values.config,
      tool_ids: values.tool_ids ?? [],
      skill_ids: values.skill_ids ?? [],
      department_id: isPlatform ? null : (values.department_id ?? null),
    }

    setSaving(true)
    try {
      if (agentId !== undefined) {
        await updateAgent(agentId, payload)
        message.success('保存成功')
      } else {
        await createAgent(payload)
        message.success('创建成功')
      }
      navigate('/agents')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="agent-edit">
      <div className="agent-edit__header">
        <Space size={12} align="center">
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/agents')} />
          <div>
            <h2 className="page-header__title">{isEdit ? '配置智能体' : '新建智能体'}</h2>
            <p className="page-header__desc">
              配置智能体属性，并在同一页面维护其技能、工具、组件与提示词。
            </p>
          </div>
          {platformResource && <Tag color="geekblue">平台级</Tag>}
        </Space>
        <Space>
          <Button onClick={() => navigate('/agents')}>返回</Button>
          {!readonly && (
            <Button type="primary" loading={saving} onClick={() => form.submit()}>
              保存配置
            </Button>
          )}
          {readonly && canSubmit && <Tag bordered={false}>产品级资源只读</Tag>}
        </Space>
      </div>

      <Tabs
        defaultActiveKey="config"
        items={[
          {
            key: 'config',
            label: '配置',
            children: (
              <Form<AgentFormValues>
                form={form}
                layout="vertical"
                scrollToFirstError
                onFinish={handleFinish}
                disabled={readonly}
              >
                <Spin spinning={loading}>
                  <div className="agent-edit__body">
                    <div className="agent-edit__main">
                      <BasicSection deptTreeData={deptTreeData} showDepartment={!isPlatform} />
                      <ModelSection />
                      <PromptSection />
                      <MemorySection />
                      <ConversationSection />
                      <ChannelSection />
                      <ToolSkillSection tools={tools} skills={skills} />
                      <KnowledgeSection />
                      <OtherSection />
                      <ExtensionSection components={components} />
                    </div>

                    <aside className="agent-edit__aside">
                      <Anchor
                        affix={false}
                        items={ANCHOR_ITEMS}
                        targetOffset={96}
                        className="agent-edit__anchor"
                      />
                    </aside>
                  </div>
                </Spin>
              </Form>
            ),
          },
          {
            key: 'resources',
            label: '技能与资源',
            children: (
              <Spin spinning={loading}>
                <AgentResourcesTab agentId={isEdit ? agentId : undefined} />
              </Spin>
            ),
          },
          ...(isEdit && !platformResource
            ? [
                {
                  key: 'visibility',
                  label: '可见范围',
                  children: (
                    <Spin spinning={loading}>
                      <AgentVisibilityTab agentId={agentId as string} />
                    </Spin>
                  ),
                },
              ]
            : []),
          ...(isEdit && isPlatform && platformResource
            ? [
                {
                  key: 'tenants',
                  label: '开通租户',
                  children: (
                    <Spin spinning={loading}>
                      <AgentTenantsTab agentId={agentId as string} />
                    </Spin>
                  ),
                },
              ]
            : []),
        ]}
      />
    </div>
  )
}
