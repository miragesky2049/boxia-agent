import { ArrowLeftOutlined, SaveOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { App, Button, Input, Space, Spin, Switch, Tag } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  type Node,
  type OnConnect,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { getWorkflow, updateWorkflow, validateGraph } from '../../api/workflows'
import { toolsApi } from '../../api/resources'
import { useTenant } from '../../tenant/TenantContext'
import { isPlatformTenant } from '../../api/workflows'
import { useWorkflowStore, type WorkflowNodeData, type WorkflowNodeType } from './store/workflowStore'
import { NodePalette } from './components/NodePalette'
import { NodeConfigDrawer } from './components/NodeConfigDrawer'
import { WorkflowCanvasNode } from './components/nodes/WorkflowCanvasNode'

const nodeTypes = {
  workflowNode: WorkflowCanvasNode,
}

type CanvasNode = Node<WorkflowNodeData>

export default function WorkflowEditPage() {
  const navigate = useNavigate()
  const params = useParams<{ id: string }>()
  const workflowId = params.id ?? ''
  const { message } = App.useApp()
  const { isPlatform } = useTenant()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [tenantId, setTenantId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isEnabled, setIsEnabled] = useState(true)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [toolOptions, setToolOptions] = useState<Array<{ value: string; label: string }>>([])

  const nodes = useWorkflowStore((s) => s.nodes)
  const edges = useWorkflowStore((s) => s.edges)
  const onNodesChange = useWorkflowStore((s) => s.onNodesChange)
  const onEdgesChange = useWorkflowStore((s) => s.onEdgesChange)
  const onConnect = useWorkflowStore((s) => s.onConnect)
  const addNodeOfType = useWorkflowStore((s) => s.addNodeOfType)
  const selectNode = useWorkflowStore((s) => s.selectNode)
  const loadFromGraph = useWorkflowStore((s) => s.loadFromGraph)
  const serializeToGraph = useWorkflowStore((s) => s.serializeToGraph)
  const reset = useWorkflowStore((s) => s.reset)

  useEffect(() => {
    reset()
    if (!workflowId) {
      setLoading(false)
      return
    }
    setLoading(true)
    getWorkflow(workflowId)
      .then((detail) => {
        setTenantId(detail.tenant_id)
        setName(detail.name)
        setDescription(detail.description)
        setIsEnabled(detail.is_enabled)
        loadFromGraph(detail.graph)
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : '加载工作流失败')
      })
      .finally(() => setLoading(false))
    return () => reset()
  }, [workflowId, message, loadFromGraph, reset])

  useEffect(() => {
    toolsApi
      .list({ page: 1, page_size: 200, is_enabled: true })
      .then((page) => {
        setToolOptions(
          page.items.map((t) => ({
            value: t.id,
            label: t.name,
          })),
        )
      })
      .catch(() => {
        // 工具列表加载失败不阻塞画布
      })
  }, [])

  const readOnly = !isPlatform && tenantId !== null && isPlatformTenant(tenantId)

  const handleNodeClick = useCallback(
    (_: unknown, node: CanvasNode) => {
      selectNode(node.id)
      setDrawerOpen(true)
    },
    [selectNode],
  )

  const handlePaneClick = useCallback(() => {
    selectNode(null)
    setDrawerOpen(false)
  }, [selectNode])

  const handleAddNode = useCallback(
    (type: WorkflowNodeType) => {
      addNodeOfType(type)
      setDrawerOpen(true)
    },
    [addNodeOfType],
  )

  const graphPayload = useMemo(
    () => ({
      name,
      description,
      graph: serializeToGraph(),
      is_enabled: isEnabled,
    }),
    [name, description, isEnabled, serializeToGraph],
  )

  const handleSave = async () => {
    if (!name.trim()) {
      message.warning('请填写工作流名称')
      return
    }
    setSaving(true)
    try {
      await updateWorkflow(workflowId, graphPayload)
      message.success('已保存')
      navigate('/workflows')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleValidate = async () => {
    try {
      const result = await validateGraph(graphPayload)
      if (result.valid) {
        message.success(`校验通过：${result.node_count} 个节点，${result.edge_count} 条边`)
      } else {
        message.warning('图校验未通过')
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '校验失败')
    }
  }

  if (loading) {
    return (
      <div className="page-card" style={{ textAlign: 'center', padding: 80 }}>
        <Spin />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 96px)' }}>
      <div className="page-card" style={{ padding: '12px 16px', marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/workflows')}>
            返回
          </Button>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="工作流名称"
            style={{ width: 240 }}
            disabled={readOnly}
          />
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述（可选）"
            style={{ width: 280 }}
            disabled={readOnly}
          />
          <Switch
            checked={isEnabled}
            onChange={setIsEnabled}
            checkedChildren="启用"
            unCheckedChildren="停用"
            disabled={readOnly}
          />
          {tenantId && isPlatformTenant(tenantId) ? (
            <Tag color="geekblue" bordered={false}>平台级</Tag>
          ) : (
            <Tag color="green" bordered={false}>本租户</Tag>
          )}
          <Space style={{ marginLeft: 'auto' }}>
            <Button icon={<ThunderboltOutlined />} onClick={handleValidate} disabled={readOnly}>
              校验图
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
              disabled={readOnly}
            >
              保存
            </Button>
          </Space>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <NodePalette onAdd={handleAddNode} />
        <div style={{ flex: 1, background: '#f5f7fa' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange as OnNodesChange}
            onEdgesChange={onEdgesChange as OnEdgesChange}
            onConnect={onConnect as OnConnect}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#d9d9d9" gap={16} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
      </div>

      <NodeConfigDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        toolOptions={toolOptions}
      />
    </div>
  )
}
