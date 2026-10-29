import { ArrowLeftOutlined, HistoryOutlined, PlayCircleOutlined, SaveOutlined } from '@ant-design/icons'
import { App, Button, Input, Space, Spin, Tag } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type OnConnect,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { getApp, getAppGraph, saveAppGraph, updateApp, type DebugNodeState } from '../../api/apps'
import { NodeConfigDrawer } from './components/NodeConfigDrawer'
import { NodePalette, APP_NODE_DND_MIME } from './components/NodePalette'
import { RunDebugModal } from './components/RunDebugModal'
import { RunLogPanel } from './components/RunLogPanel'
import { CanvasNode } from './components/CanvasNode'
import { VersionHistoryDrawer } from './components/VersionHistoryDrawer'
import { useAppStore, type NodeData, type NodeType } from './store/appStore'

const nodeTypes = { appNode: CanvasNode }

type AppNode = Node<NodeData>

function AppEditCanvas() {
  const navigate = useNavigate()
  const params = useParams<{ id: string }>()
  const appId = params.id ?? ''
  const { message } = App.useApp()
  const { screenToFlowPosition } = useReactFlow()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [runtimeMode, setRuntimeMode] = useState<'dag' | 'agent_loop' | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [debugStates, setDebugStates] = useState<Record<string, DebugNodeState>>({})
  const [debugRunning, setDebugRunning] = useState(false)
  const [finalResult, setFinalResult] = useState<Record<string, unknown> | null>(null)
  const [logPanelOpen, setLogPanelOpen] = useState(false)
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false)

  const nodes = useAppStore((s) => s.nodes)
  const edges = useAppStore((s) => s.edges)
  const onNodesChange = useAppStore((s) => s.onNodesChange)
  const onEdgesChange = useAppStore((s) => s.onEdgesChange)
  const onConnect = useAppStore((s) => s.onConnect)
  const addNodeOfType = useAppStore((s) => s.addNodeOfType)
  const selectNode = useAppStore((s) => s.selectNode)
  const loadFromGraph = useAppStore((s) => s.loadFromGraph)
  const serializeToGraph = useAppStore((s) => s.serializeToGraph)
  const reset = useAppStore((s) => s.reset)

  useEffect(() => {
    reset()
    if (!appId) {
      setLoading(false)
      return
    }
    setLoading(true)
    Promise.all([getApp(appId), getAppGraph(appId).catch(() => null)])
      .then(([app, graphData]) => {
        setName(app.name)
        setDescription(app.description ?? '')
        if (graphData) {
          loadFromGraph(graphData.graph)
          setRuntimeMode(graphData.runtime_mode)
        }
      })
      .catch((error: unknown) => {
        message.error(error instanceof Error ? error.message : '加载应用失败')
      })
      .finally(() => setLoading(false))
    return () => reset()
  }, [appId, message, loadFromGraph, reset])

  const handleNodeClick = useCallback(
    (_: unknown, node: AppNode) => {
      if (debugRunning) return
      selectNode(node.id)
      setDrawerOpen(true)
    },
    [selectNode, debugRunning],
  )

  const handlePaneClick = useCallback(() => {
    if (debugRunning) return
    selectNode(null)
    setDrawerOpen(false)
  }, [selectNode, debugRunning])

  const handleAddNode = useCallback(
    (type: NodeType) => {
      if (debugRunning) {
        message.warning('试运行期间画布只读')
        return
      }
      const error = addNodeOfType(type)
      if (error) {
        message.warning(error)
        return
      }
      setDrawerOpen(true)
    },
    [addNodeOfType, message, debugRunning],
  )

  const handleConnect = useCallback<OnConnect>(
    (connection) => {
      if (debugRunning) return
      const error = onConnect(connection)
      if (error) message.warning(error)
    },
    [onConnect, message, debugRunning],
  )

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      if (debugRunning) {
        message.warning('试运行期间画布只读')
        return
      }
      const type = event.dataTransfer.getData(APP_NODE_DND_MIME) as NodeType | ''
      if (!type) return
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      const error = addNodeOfType(type, position)
      if (error) {
        message.warning(error)
        return
      }
      setDrawerOpen(true)
    },
    [screenToFlowPosition, addNodeOfType, message, debugRunning],
  )

  // 把 debug 状态映射到画布节点的 data.debugStatus，供 CanvasNode 高亮
  const nodesWithDebug = useMemo<Array<Node<NodeData>>>(() => {
    if (Object.keys(debugStates).length === 0) return nodes
    return nodes.map((node) => {
      const state = debugStates[node.id]
      if (!state) return node
      return {
        ...node,
        data: { ...node.data, debugStatus: state.status },
      }
    })
  }, [nodes, debugStates])

  const handleDebugStatesChange = useCallback(
    (states: Record<string, DebugNodeState>) => {
      setDebugStates(states)
    },
    [],
  )

  const handleRunningChange = useCallback(
    (running: boolean) => {
      setDebugRunning(running)
      if (running) setLogPanelOpen(true)
    },
    [],
  )

  const handleFinalResult = useCallback(
    (result: Record<string, unknown> | null) => {
      setFinalResult(result)
      if (result) setLogPanelOpen(true)
    },
    [],
  )

  const graphForDebug = useMemo(
    () => serializeToGraph(),
    [serializeToGraph, nodes, edges],
  )

  const handleSave = async () => {
    if (!name.trim()) {
      message.warning('请填写应用名称')
      return
    }
    if (debugRunning) {
      message.warning('试运行进行中，请稍后再保存')
      return
    }
    setSaving(true)
    try {
      await updateApp(appId, { name: name.trim(), description })
      const graph = serializeToGraph()
      const result = await saveAppGraph(appId, graph)
      setRuntimeMode(result.runtime_mode)
      const changed = result.versioned_fields?.length ?? 0
      message.success(
        changed > 0 ? `已保存，${changed} 个字段已生成新版本` : '已保存',
      )
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
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
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/apps')}>
            返回
          </Button>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="应用名称"
            style={{ width: 240 }}
            disabled={debugRunning}
          />
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述（可选）"
            style={{ width: 280 }}
            disabled={debugRunning}
          />
          {runtimeMode && <Tag color={runtimeMode === 'agent_loop' ? 'purple' : 'blue'}>{runtimeMode}</Tag>}
          {debugRunning && <Tag color="orange">试运行中（画布只读）</Tag>}
          <Space style={{ marginLeft: 'auto' }}>
            <Button
              icon={<HistoryOutlined />}
              onClick={() => setVersionDrawerOpen(true)}
              disabled={debugRunning}
            >
              版本
            </Button>
            <Button
              icon={<PlayCircleOutlined />}
              onClick={() => setDebugOpen(true)}
              disabled={debugRunning}
            >
              试运行
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
              disabled={debugRunning}
            >
              保存
            </Button>
          </Space>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <NodePalette onAdd={handleAddNode} />
        <div style={{ flex: 1, background: '#f5f7fa', position: 'relative' }} onDrop={handleDrop} onDragOver={handleDragOver}>
          <ReactFlow
            nodes={nodesWithDebug}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange as OnNodesChange}
            onEdgesChange={onEdgesChange as OnEdgesChange}
            onConnect={handleConnect as OnConnect}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            nodesDraggable={!debugRunning}
            nodesConnectable={!debugRunning}
            elementsSelectable={!debugRunning}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#d9d9d9" gap={16} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
      </div>

      <NodeConfigDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <VersionHistoryDrawer
        open={versionDrawerOpen}
        applicationId={appId}
        onClose={() => setVersionDrawerOpen(false)}
      />

      <RunDebugModal
        open={debugOpen}
        graph={graphForDebug}
        onClose={() => setDebugOpen(false)}
        onNodeStateChange={handleDebugStatesChange}
        onRunningChange={handleRunningChange}
        onFinalResult={handleFinalResult}
      />

      <RunLogPanel
        open={logPanelOpen}
        running={debugRunning}
        states={debugStates}
        finalResult={finalResult}
        onClose={() => setLogPanelOpen(false)}
      />
    </div>
  )
}

export default function AppEditPage() {
  return (
    <ReactFlowProvider>
      <AppEditCanvas />
    </ReactFlowProvider>
  )
}
