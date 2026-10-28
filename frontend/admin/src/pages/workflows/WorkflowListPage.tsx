import {
  AppstoreOutlined,
  NodeIndexOutlined,
  PlusOutlined,
  ShareAltOutlined,
} from '@ant-design/icons'
import { App, Button, Input, Popconfirm, Space, Switch, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  cloneWorkflowFromTemplate,
  createWorkflow,
  deleteTemplate,
  deleteWorkflow,
  getWorkflow,
  listTemplates,
  listWorkflows,
  updateWorkflow,
} from '../../api/workflows'
import type { WorkflowSummary, WorkflowTemplate } from '../../api/workflows'
import { isPlatformTenant } from '../../api/workflows'
import { useTenant } from '../../tenant/TenantContext'
import { buildDefaultSkeletonGraph } from './defaultGraph'
import TemplatePickerModal from './TemplatePickerModal'
import './WorkflowListPage.css'

export default function WorkflowListPage() {
  const navigate = useNavigate()
  const { message } = App.useApp()
  const { isPlatform } = useTenant()

  const [activeTab, setActiveTab] = useState<'workflows' | 'templates'>('workflows')
  const [items, setItems] = useState<WorkflowSummary[]>([])
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([])
  const [total, setTotal] = useState(0)
  const [templateTotal, setTemplateTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)

  const loadWorkflows = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listWorkflows({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载工作流失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, message])

  const loadTemplates = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listTemplates({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
      })
      setTemplates(result.items)
      setTemplateTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载模板失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, message])

  useEffect(() => {
    if (activeTab === 'workflows') {
      void loadWorkflows()
    } else {
      void loadTemplates()
    }
  }, [activeTab, loadWorkflows, loadTemplates])

  const handleDeleteWorkflow = async (id: string) => {
    try {
      await deleteWorkflow(id)
      message.success('已删除')
      if (items.length === 1 && page > 1) {
        setPage(page - 1)
      } else {
        await loadWorkflows()
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleDeleteTemplate = async (id: string) => {
    try {
      await deleteTemplate(id)
      message.success('已删除模板')
      await loadTemplates()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除模板失败')
    }
  }

  const handleToggleEnabled = async (record: WorkflowSummary, enabled: boolean) => {
    try {
      const detail = await getWorkflow(record.id)
      await updateWorkflow(record.id, {
        name: detail.name,
        description: detail.description,
        graph: detail.graph,
        is_enabled: enabled,
        visibility_mode: detail.visibility_mode,
      })
      message.success(enabled ? '已启用' : '已停用')
      await loadWorkflows()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败')
    }
  }

  const handlePickBlank = async (name: string) => {
    try {
      await createWorkflow({
        name,
        description: '',
        graph: buildDefaultSkeletonGraph(),
        is_enabled: true,
      })
      message.success('已创建空白工作流')
      setPickerOpen(false)
      await loadWorkflows()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '创建失败')
    }
  }

  const handlePickTemplate = async (template: WorkflowTemplate, name: string) => {
    try {
      await cloneWorkflowFromTemplate(template.id, { name, description: null })
      message.success(`已从模板「${template.name}」创建`)
      setPickerOpen(false)
      await loadWorkflows()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '克隆失败')
    }
  }

  const workflowColumns: ColumnsType<WorkflowSummary> = [
    {
      title: '工作流',
      dataIndex: 'name',
      key: 'name',
      render: (_: unknown, record: WorkflowSummary) => (
        <div className="workflow-cell">
          <NodeIndexOutlined className="workflow-cell__icon" />
          <div>
            <div className="resource-name">
              {record.name}
              {isPlatformTenant(record.tenant_id) ? (
                <Tag color="geekblue" bordered={false} style={{ marginLeft: 8 }}>
                  平台级
                </Tag>
              ) : (
                !isPlatform && (
                  <Tag color="green" bordered={false} style={{ marginLeft: 8 }}>
                    本租户
                  </Tag>
                )
              )}
            </div>
            <div className="resource-desc">{record.description || '暂无描述'}</div>
          </div>
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 130,
      render: (enabled: boolean, record: WorkflowSummary) => (
        <Switch
          size="small"
          checked={enabled}
          checkedChildren="启用"
          unCheckedChildren="停用"
          disabled={isPlatformTenant(record.tenant_id) && !isPlatform}
          onChange={(checked) => handleToggleEnabled(record, checked)}
        />
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 240,
      render: (_: unknown, record: WorkflowSummary) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            onClick={() => navigate(`/workflows/${record.id}/edit`)}
          >
            编辑
          </Button>
          {(!isPlatformTenant(record.tenant_id) || isPlatform) && (
            <Popconfirm
              title="确认删除该工作流？"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDeleteWorkflow(record.id)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const templateColumns: ColumnsType<WorkflowTemplate> = [
    {
      title: '模板',
      dataIndex: 'name',
      key: 'name',
      render: (_: unknown, record: WorkflowTemplate) => (
        <div className="workflow-cell">
          <AppstoreOutlined className="workflow-cell__icon workflow-cell__icon--blue" />
          <div>
            <div className="resource-name">
              {record.name}
              {record.category ? (
                <Tag color="blue" bordered={false} style={{ marginLeft: 8 }}>
                  {record.category}
                </Tag>
              ) : null}
            </div>
            <div className="resource-desc">{record.description || '暂无描述'}</div>
          </div>
        </div>
      ),
    },
    {
      title: '启用',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 100,
      render: (enabled: boolean) =>
        enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: unknown, record: WorkflowTemplate) =>
        isPlatform ? (
          <Space size={4}>
            <Button type="link" size="small" disabled>
              编辑
            </Button>
            <Popconfirm
              title="确认删除该模板？"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDeleteTemplate(record.id)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ) : (
          <Tag bordered={false} icon={<ShareAltOutlined />}>
            可在新建时选用
          </Tag>
        ),
    },
  ]

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">工作流</h2>
          <p className="page-header__desc">
            以 DAG 节点编排复杂业务流：Start → LLM → Tool → End。
          </p>
        </div>
        {activeTab === 'workflows' && (
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
            新建工作流
          </Button>
        )}
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key as 'workflows' | 'templates')
          setPage(1)
          setKeyword('')
        }}
        items={[
          { key: 'workflows', label: '我的工作流' },
          { key: 'templates', label: '模板市场' },
        ]}
      />

      <div className="page-toolbar">
        <Input.Search
          allowClear
          placeholder="搜索名称"
          style={{ width: 280 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Tag color="blue" bordered={false}>
          共 {activeTab === 'workflows' ? total : templateTotal} 项
        </Tag>
      </div>

      {activeTab === 'workflows' ? (
        <Table<WorkflowSummary>
          rowKey="id"
          columns={workflowColumns}
          dataSource={items}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 条`,
            onChange: (nextPage, nextSize) => {
              setPage(nextSize !== pageSize ? 1 : nextPage)
              setPageSize(nextSize)
            },
          }}
        />
      ) : (
        <Table<WorkflowTemplate>
          rowKey="id"
          columns={templateColumns}
          dataSource={templates}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: templateTotal,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (count) => `共 ${count} 条`,
            onChange: (nextPage, nextSize) => {
              setPage(nextSize !== pageSize ? 1 : nextPage)
              setPageSize(nextSize)
            },
          }}
        />
      )}

      <TemplatePickerModal
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPickBlank={handlePickBlank}
        onPickTemplate={handlePickTemplate}
      />
    </div>
  )
}
