import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  DownOutlined,
  EnvironmentOutlined,
  HistoryOutlined,
  LayoutOutlined,
  PictureOutlined,
  RedoOutlined,
  SafetyOutlined,
  SaveOutlined,
  UndoOutlined,
} from '@ant-design/icons'
import { App, Button, Dropdown, Input, Modal, Space, Spin, Tag, Tooltip } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
  type Node,
  type OnConnect,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { getApp, getAppGraph, saveAppGraph, updateApp } from '../../api/apps'
import { NodeConfigDrawer } from './components/NodeConfigDrawer'
import { NodePalette, APP_NODE_DND_MIME } from './components/NodePalette'
import { CanvasNode } from './components/CanvasNode'
import { StickyNode } from './components/StickyNode'
import { EdgeWithPlus } from './components/EdgeWithPlus'
import { VersionHistoryDrawer } from './components/VersionHistoryDrawer'
import { VisibilityScopeDrawer } from './components/VisibilityScopeDrawer'
import { useAppStore, listOutputFields, type NodeData, type NodeType } from './store/appStore'

const nodeTypes = { appNode: CanvasNode, sticky: StickyNode }
const edgeTypes = { default: EdgeWithPlus }

type AppNode = Node<NodeData>

function AppEditCanvas() {
  const navigate = useNavigate()
  const params = useParams<{ id: string }>()
  const appId = params.id ?? ''
  const { message, modal } = App.useApp()
  const { screenToFlowPosition, setCenter, zoomTo, fitView } = useReactFlow()
  const { zoom } = useViewport()

  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [runtimeMode, setRuntimeMode] = useState<'dag' | 'agent_loop' | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false)
  const [variableCheckOpen, setVariableCheckOpen] = useState(false)
  const [visibilityDrawerOpen, setVisibilityDrawerOpen] = useState(false)

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
  const undo = useAppStore((s) => s.undo)
  const redo = useAppStore((s) => s.redo)
  const past = useAppStore((s) => s.past)
  const future = useAppStore((s) => s.future)

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

  // 滚动至选中节点：把视口中心定位到选中节点
  const handleLocateSelected = useCallback(() => {
    if (!selectedNodeId) {
      message.warning('请先选中一个节点')
      return
    }
    const node = nodes.find((n) => n.id === selectedNodeId)
    if (!node) return
    const x = node.position.x + (node.measured?.width ?? 160) / 2
    const y = node.position.y + (node.measured?.height ?? 80) / 2
    void setCenter(x, y, { zoom: 1.2, duration: 300 })
  }, [selectedNodeId, nodes, setCenter, message])

  // 变量检查：扫描所有节点 config 中的 {{#nodeId.field#}} 引用，列出未定义/未连接的引用
  const variableReport = useMemo(() => {
    const definedOutputs = new Map<string, string[]>()
    nodes.forEach((n) => {
      const type = n.data.nodeType
      const outputs = listOutputFields(type)
      definedOutputs.set(n.id, outputs)
    })
    const refs: Array<{ nodeId: string; raw: string; valid: boolean; reason: string }> = []
    const refRegex = /\{\{#([\w.]+)#\}\}/g
    nodes.forEach((n) => {
      const cfgStr = JSON.stringify(n.data.config ?? {})
      let m: RegExpExecArray | null
      while ((m = refRegex.exec(cfgStr)) !== null) {
        const raw = m[1]
        const [nodeId, field] = raw.split('.')
        const outputs = definedOutputs.get(nodeId)
        if (!outputs) {
          refs.push({ nodeId: n.id, raw, valid: false, reason: `引用了不存在的节点 ${nodeId}` })
        } else if (field && !outputs.includes(field)) {
          refs.push({ nodeId: n.id, raw, valid: false, reason: `节点 ${nodeId} 无输出字段 ${field}` })
        } else {
          refs.push({ nodeId: n.id, raw, valid: true, reason: 'OK' })
        }
      }
    })
    const startNode = nodes.find((n) => n.data.nodeType === 'start')
    const endNode = nodes.find((n) => n.data.nodeType === 'end')
    const issues: string[] = []
    if (!startNode) issues.push('缺少开始节点')
    if (!endNode) issues.push('缺少结束节点')
    const nodesWithoutIncoming = nodes.filter((n) => {
      if (n.data.nodeType === 'start' || n.data.nodeType === 'sticky') return false
      return !edges.some((e) => e.target === n.id)
    })
    if (nodesWithoutIncoming.length > 0) {
      issues.push(`以下节点没有上游连线：${nodesWithoutIncoming.map((n) => n.data.label).join('、')}`)
    }
    const nodesWithoutOutgoing = nodes.filter((n) => {
      if (n.data.nodeType === 'end' || n.data.nodeType === 'sticky') return false
      return !edges.some((e) => e.source === n.id)
    })
    if (nodesWithoutOutgoing.length > 0) {
      issues.push(`以下节点没有下游连线：${nodesWithoutOutgoing.map((n) => n.data.label).join('、')}`)
    }
    return { refs, issues }
  }, [nodes, edges])

  // 画布键盘快捷键：Delete 删除选中节点、Ctrl+C 复制、Ctrl+V 粘贴、Ctrl+Z/Y 撤销重做、Alt+L 定位
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isEditable =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target?.isContentEditable
      if (isEditable) return

      // Alt+L 定位选中节点
      if (e.altKey && e.key.toLowerCase() === 'l') {
        e.preventDefault()
        handleLocateSelected()
        return
      }

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
      } else if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
      } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        redo()
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        redo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedNodeId, removeNode, copyNode, pasteNode, selectNode, undo, redo, message, handleLocateSelected])

  const handleNodeClick = useCallback(
    (_: unknown, node: AppNode) => {
      selectNode(node.id)
      // 注释便签节点双击直接编辑，不打开配置抽屉
      if (node.data.nodeType !== 'sticky') {
        setDrawerOpen(true)
      }
    },
    [selectNode],
  )

  const handlePaneClick = useCallback(() => {
    selectNode(null)
    setDrawerOpen(false)
  }, [selectNode])

  const handleAddNode = useCallback(
    (type: NodeType) => {
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
    [addNodeOfType, message],
  )

  const handleConnect = useCallback<OnConnect>(
    (connection) => {
      const error = onConnect(connection)
      if (error) message.warning(error)
    },
    [onConnect, message],
  )

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
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
    [screenToFlowPosition, addNodeOfType, message],
  )

  const handleSave = async () => {
    if (!name.trim()) {
      message.warning('请填写应用名称')
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

  // 自动布局：按拓扑层级从左到右排列
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

  // 导出画布为 PNG
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
          />
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述（可选）"
            style={{ width: 280 }}
          />
          {runtimeMode && <Tag color={runtimeMode === 'agent_loop' ? 'purple' : 'blue'}>{runtimeMode}</Tag>}
          <Space style={{ marginLeft: 'auto' }}>
            <Button
              icon={<LayoutOutlined />}
              onClick={handleAutoLayout}
              disabled={nodes.length === 0}
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
            >
              版本
            </Button>
            <Tooltip title="定位到选中节点（Alt+L）">
              <Button
                icon={<EnvironmentOutlined />}
                onClick={handleLocateSelected}
                disabled={!selectedNodeId}
              >
                定位
              </Button>
            </Tooltip>
            <Button
              icon={<SafetyOutlined />}
              onClick={() => setVisibilityDrawerOpen(true)}
            >
              可见范围
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
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
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onNodesChange={onNodesChange as OnNodesChange}
              onEdgesChange={onEdgesChange as OnEdgesChange}
              onConnect={handleConnect as OnConnect}
              onNodeClick={handleNodeClick}
              onPaneClick={handlePaneClick}
              fitView
              fitViewOptions={{ padding: 0.3, maxZoom: 0.9 }}
              defaultViewport={{ x: 0, y: 0, zoom: 0.85 }}
              minZoom={0.3}
              maxZoom={1.5}
              proOptions={{ hideAttribution: true }}
            >
              <Background color="#d9d9d9" gap={16} />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable />
            </ReactFlow>

            {/* 底部浮动工具栏：undo/redo + 变量检查 */}
            <div
              style={{
                position: 'absolute',
                bottom: 16,
                left: '50%',
                transform: 'translateX(-50%)',
                display: 'flex',
                gap: 4,
                padding: '4px 8px',
                background: '#fff',
                borderRadius: 8,
                boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                border: '1px solid #f0f0f0',
                zIndex: 20,
                alignItems: 'center',
              }}
            >
              <Tooltip title="撤销 (Ctrl+Z)">
                <Button
                  size="small"
                  type="text"
                  icon={<UndoOutlined />}
                  disabled={past.length === 0}
                  onClick={undo}
                />
              </Tooltip>
              <Tooltip title="重做 (Ctrl+Shift+Z)">
                <Button
                  size="small"
                  type="text"
                  icon={<RedoOutlined />}
                  disabled={future.length === 0}
                  onClick={redo}
                />
              </Tooltip>
              <div style={{ width: 1, height: 16, background: '#e8e8e8', margin: '0 4px' }} />
              <Button
                size="small"
                type="text"
                icon={<CheckCircleOutlined />}
                onClick={() => setVariableCheckOpen(true)}
              >
                变量检查
                {variableReport.issues.length > 0 && (
                  <Tag color="orange" style={{ marginLeft: 4 }}>{variableReport.issues.length}</Tag>
                )}
              </Button>
              <div style={{ width: 1, height: 16, background: '#e8e8e8', margin: '0 4px' }} />
              <Dropdown
                trigger={['click']}
                placement="topCenter"
                menu={{
                  items: [
                    { key: '25', label: '缩放到 25%' },
                    { key: '50', label: '缩放到 50%' },
                    { key: '75', label: '缩放到 75%' },
                    { key: '100', label: '缩放到 100%' },
                    { key: '150', label: '缩放到 150%' },
                    { key: '200', label: '缩放到 200%' },
                    { type: 'divider' },
                    { key: 'fit', label: '自适应视图' },
                  ],
                  onClick: ({ key }) => {
                    if (key === 'fit') {
                      void fitView({ padding: 0.3, duration: 300 })
                    } else {
                      void zoomTo(Number(key) / 100, { duration: 200 })
                    }
                  },
                }}
              >
                <Button size="small" type="text" style={{ minWidth: 72 }}>
                  {Math.round(zoom * 100)}% <DownOutlined style={{ fontSize: 10, marginLeft: 4 }} />
                </Button>
              </Dropdown>
            </div>
          </div>
        </Dropdown>
      </div>

      <NodeConfigDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />

      <VersionHistoryDrawer
        open={versionDrawerOpen}
        applicationId={appId}
        onClose={() => setVersionDrawerOpen(false)}
      />

      <VisibilityScopeDrawer
        open={visibilityDrawerOpen}
        applicationId={appId}
        onClose={() => setVisibilityDrawerOpen(false)}
      />

      <Modal
        title="变量检查"
        open={variableCheckOpen}
        onCancel={() => setVariableCheckOpen(false)}
        footer={<Button onClick={() => setVariableCheckOpen(false)}>关闭</Button>}
        width={560}
      >
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontWeight: 500, marginBottom: 8 }}>结构问题</div>
          {variableReport.issues.length === 0 ? (
            <div style={{ color: '#52c41a' }}>✓ 无结构问题</div>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 20, color: '#fa8c16' }}>
              {variableReport.issues.map((issue, i) => (
                <li key={i}>{issue}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <div style={{ fontWeight: 500, marginBottom: 8 }}>变量引用（{'{{#nodeId.field#}}'}）</div>
          {variableReport.refs.length === 0 ? (
            <div style={{ color: '#8c8c8c' }}>画布中未发现变量引用</div>
          ) : (
            <div style={{ maxHeight: 300, overflowY: 'auto', fontSize: 12 }}>
              {variableReport.refs.map((ref, i) => (
                <div
                  key={i}
                  style={{
                    padding: '4px 8px',
                    marginBottom: 4,
                    background: ref.valid ? '#f6ffed' : '#fff2f0',
                    border: `1px solid ${ref.valid ? '#b7eb8f' : '#ffccc7'}`,
                    borderRadius: 4,
                    fontFamily: 'monospace',
                  }}
                >
                  <span style={{ color: ref.valid ? '#52c41a' : '#ff4d4f' }}>
                    {ref.valid ? '✓' : '✗'}
                  </span>
                  <span style={{ marginLeft: 8 }}>{ref.raw}</span>
                  <span style={{ marginLeft: 8, color: '#8c8c8c' }}>— {ref.reason}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
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
