import { ArrowLeftOutlined, FileTextOutlined, HistoryOutlined, LayoutOutlined, PictureOutlined, PlayCircleOutlined, SaveOutlined } from '@ant-design/icons'
import { App, Button, Dropdown, Input, Space, Spin, Tag } from 'antd'
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
import { StickyNode } from './components/StickyNode'
import { EdgeWithPlus } from './components/EdgeWithPlus'
import { VersionHistoryDrawer } from './components/VersionHistoryDrawer'
import { useAppStore, type NodeData, type NodeType } from './store/appStore'

const nodeTypes = { appNode: CanvasNode, sticky: StickyNode }
const edgeTypes = { default: EdgeWithPlus }

type AppNode = Node<NodeData>

function AppEditCanvas() {
  const navigate = useNavigate()
  const params = useParams<{ id: string }>()
  const appId = params.id ?? ''
  const { message, modal } = App.useApp()
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
  const removeNode = useAppStore((s) => s.removeNode)
  const copyNode = useAppStore((s) => s.copyNode)
  const pasteNode = useAppStore((s) => s.pasteNode)
  const selectedNodeId = useAppStore((s) => s.selectedNodeId)

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

  // 画布键盘快捷键：Delete 删除选中节点、Ctrl+C 复制、Ctrl+V 粘贴
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (debugRunning) return
      const target = e.target as HTMLElement | null
      const isEditable =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable
      if (isEditable) return

      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNodeId) {
        e.preventDefault()
        removeNode(selectedNodeId)
        selectNode(null)
        setDrawerOpen(false)
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c' && selectedNodeId) {
        e.preventDefault()
        copyNode(selectedNodeId)
        message.success('已复制节点，可按 Ctrl+V 粘贴')
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
        e.preventDefault()
        pasteNode()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [debugRunning, selectedNodeId, removeNode, copyNode, pasteNode, selectNode, message])

  const handleNodeClick = useCallback(
    (_: unknown, node: AppNode) => {
      if (debugRunning) return
      selectNode(node.id)
      // 注释便签节点双击直接编辑，不打开配置抽屉
      if (node.data.nodeType !== 'sticky') {
        setDrawerOpen(true)
      }
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
      // 注释便签节点双击直接编辑内容，不打开配置抽屉
      if (type !== 'sticky') {
        setDrawerOpen(true)
      }
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
      if (type !== 'sticky') {
        setDrawerOpen(true)
      }
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

  // 自动布局：按拓扑层级从左到右排列（参考 dify/coze 的"整理节点"）
  const handleAutoLayout = useCallback(() => {
    if (nodes.length === 0) return
    // 计算每个节点的层级
    const inDegree = new Map<string, number>()
    nodes.forEach((n) => inDegree.set(n.id, 0))
    edges.forEach((e) => inDegree.set(e.target, (inDegree.get(e.target) ?? 0) + 1))

    const level = new Map<string, number>()
    const queue: string[] = []
    inDegree.forEach((d, id) => {
      if (d === 0) {
        level.set(id, 0)
        queue.push(id)
      }
    })

    while (queue.length > 0) {
      const id = queue.shift()!
      const lvl = level.get(id) ?? 0
      edges
        .filter((e) => e.source === id)
        .forEach((e) => {
          const nextLvl = (level.get(e.target) ?? 0)
          if (lvl + 1 > nextLvl) level.set(e.target, lvl + 1)
          inDegree.set(e.target, (inDegree.get(e.target) ?? 1) - 1)
          if ((inDegree.get(e.target) ?? 0) === 0) queue.push(e.target)
        })
    }

    // 每层的节点按 y 位置堆叠
    const levelNodes = new Map<number, string[]>()
    level.forEach((lvl, id) => {
      const arr = levelNodes.get(lvl) ?? []
      arr.push(id)
      levelNodes.set(lvl, arr)
    })

    const newPositions = new Map<string, { x: number; y: number }>()
    const H_GAP = 280
    const V_GAP = 120
    levelNodes.forEach((ids, lvl) => {
      ids.forEach((id, idx) => {
        newPositions.set(id, { x: lvl * H_GAP, y: idx * V_GAP })
      })
    })

    // 更新节点位置
    nodes.forEach((n) => {
      const pos = newPositions.get(n.id)
      if (pos) n.position = pos
    })

    message.success('已自动整理节点布局')
  }, [nodes, edges, message])

  // 导出画布为 PNG（参考 dify/coze 的"导出图片"）
  const handleExportImage = useCallback(async () => {
    const canvasEl = document.querySelector('.react-flow')
    if (!canvasEl) {
      message.warning('未找到画布')
      return
    }
    try {
      // 简单实现：截取画布区域
      const rect = canvasEl.getBoundingClientRect()
      const svg = canvasEl.querySelector('svg')
      if (!svg) throw new Error('no svg')

      const serializer = new XMLSerializer()
      const svgStr = serializer.serializeToString(svg)
      const img = new Image()
      const svgBlob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(svgBlob)

      img.onload = () => {
        const canvas = document.createElement('canvas')
        canvas.width = rect.width * 2
        canvas.height = rect.height * 2
        const ctx = canvas.getContext('2d')!
        ctx.fillStyle = '#f5f7fa'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.scale(2, 2)
        ctx.drawImage(img, 0, 0, rect.width, rect.height)
        URL.revokeObjectURL(url)

        canvas.toBlob((blob) => {
          if (!blob) return
          const url2 = URL.createObjectURL(blob)
          const a = document.createElement('a')
          a.href = url2
          a.download = `${name || 'workflow'}.png`
          a.click()
          URL.revokeObjectURL(url2)
          message.success('已导出画布图片')
        })
      }
      img.src = url
    } catch (error) {
      message.error('导出失败：' + (error instanceof Error ? error.message : '未知错误'))
    }
  }, [name, message])

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
              icon={<LayoutOutlined />}
              onClick={handleAutoLayout}
              disabled={debugRunning || nodes.length === 0}
              title="自动整理节点布局"
            >
              整理布局
            </Button>
            <Button
              icon={<PictureOutlined />}
              onClick={handleExportImage}
              disabled={nodes.length === 0}
              title="导出画布为 PNG 图片"
            >
              导出图片
            </Button>
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
              icon={<FileTextOutlined />}
              onClick={() => setLogPanelOpen((v) => !v)}
              type={logPanelOpen ? 'primary' : 'default'}
            >
              运行日志
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
        <Dropdown
          trigger={['contextMenu']}
          menu={{
            items: [
              { key: 'paste', label: '粘贴节点 (Ctrl+V)' },
              { key: 'layout', label: '自动整理布局' },
              { type: 'divider' },
              { key: 'clear', label: '清空画布', danger: true },
            ],
            onClick: ({ key }) => {
              if (key === 'paste') {
                pasteNode()
                message.success('已粘贴节点')
              } else if (key === 'layout') {
                handleAutoLayout()
              } else if (key === 'clear') {
                modal.confirm({
                  title: '清空画布？',
                  content: '将删除所有节点和连线，此操作不可撤销',
                  okText: '清空',
                  okButtonProps: { danger: true },
                  cancelText: '取消',
                  onOk: () => reset(),
                })
              }
            },
          }}
        >
          <div
            style={{ flex: 1, background: '#f5f7fa', position: 'relative' }}
            onDrop={handleDrop}
            onDragOver={handleDragOver}
          >
            <ReactFlow
              nodes={nodesWithDebug}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
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
        </Dropdown>
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
