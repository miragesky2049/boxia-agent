import { Button, Dropdown, Tooltip } from 'antd'
import {
  ZoomInOutlined,
  ZoomOutOutlined,
  CompressOutlined,
  FullscreenOutlined,
  PlusOutlined,
  CaretRightOutlined,
  UndoOutlined,
  RedoOutlined,
  DownOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import type { FreeLayoutPluginContext } from '@flowgram.ai/free-layout-editor'
import { CANVAS_TOKENS } from '../canvas/tokens'
import { fitView, setZoom, zoomBy } from '../canvas/adapters/flowgramContext'

// 缩放快捷档位（对齐 Coze 下拉）：选中项与当前 zoom 完全一致时高亮
const ZOOM_PRESETS = [0.5, 0.75, 1, 1.5, 2]

interface CanvasToolbarProps {
  ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>
  zoom: number
  onAddNode: () => void
  onRun: () => void
  running?: boolean
  canUndo?: boolean
  canRedo?: boolean
  onUndo?: () => void
  onRedo?: () => void
  onExportJson?: () => void
  onExportPng?: (mode: 'full' | 'viewport') => void
  exportingPng?: boolean
}

// 画布底部居中浮条（V3，对齐 Coze）：撤销/重做 | 缩放 / 适应 / 全屏 | +添加节点 | 试运行
export function CanvasToolbar({
  ctxRef,
  zoom,
  onAddNode,
  onRun,
  running,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  onExportJson,
  onExportPng,
  exportingPng,
}: CanvasToolbarProps) {
  // 画布缩放服务挂在 playground.config 上，取值路径收敛在 flowgramContext
  const applyZoom = (next: number) => setZoom(ctxRef.current, next)
  const handleZoom = (delta: number) => zoomBy(ctxRef.current, delta)
  const handleFit = () => {
    void fitView(ctxRef.current, true)
  }

  const zoomPercent = Math.round(zoom * 100)
  const zoomMenuItems = [
    ...ZOOM_PRESETS.map((preset) => ({
      key: String(preset),
      label: `${Math.round(preset * 100)}%`,
    })),
    { key: 'fit', label: '自适应' },
  ]
  const matchedPreset = ZOOM_PRESETS.find((p) => Math.abs(p - zoom) < 0.001)
  const selectedZoomKeys = matchedPreset ? [String(matchedPreset)] : []

  const handleFullscreen = () => {
    const el = document.querySelector('.gedit-playground-container') as HTMLElement | null
    if (!el) return
    if (document.fullscreenElement) {
      document.exitFullscreen?.()
    } else {
      el.requestFullscreen?.()
    }
  }

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 16,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '6px 12px',
        background: '#fff',
        borderRadius: 12,
        boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
        border: `1px solid ${CANVAS_TOKENS.border}`,
      }}
    >
      <Tooltip title="撤销 (Ctrl+Z)">
        <Button
          size="small"
          type="text"
          icon={<UndoOutlined />}
          disabled={!canUndo}
          onClick={onUndo}
        />
      </Tooltip>
      <Tooltip title="重做 (Ctrl+Shift+Z)">
        <Button
          size="small"
          type="text"
          icon={<RedoOutlined />}
          disabled={!canRedo}
          onClick={onRedo}
        />
      </Tooltip>

      <div style={{ width: 1, height: 18, background: CANVAS_TOKENS.border, margin: '0 8px' }} />

      <Tooltip title="缩小">
        <Button
          size="small"
          type="text"
          icon={<ZoomOutOutlined />}
          onClick={() => handleZoom(-0.1)}
        />
      </Tooltip>
      <Dropdown
        trigger={['click']}
        menu={{
          items: zoomMenuItems,
          selectable: true,
          selectedKeys: selectedZoomKeys,
          onClick: ({ key }) => {
            if (key === 'fit') {
              handleFit()
              return
            }
            applyZoom(Number(key))
          },
        }}
      >
        <Button size="small" type="text" style={{ fontSize: 12, color: '#6b7280', minWidth: 56 }}>
          {zoomPercent}% <DownOutlined style={{ fontSize: 9 }} />
        </Button>
      </Dropdown>
      <Tooltip title="放大">
        <Button
          size="small"
          type="text"
          icon={<ZoomInOutlined />}
          onClick={() => handleZoom(0.1)}
        />
      </Tooltip>
      <Tooltip title="适应视图">
        <Button size="small" type="text" icon={<CompressOutlined />} onClick={handleFit} />
      </Tooltip>
      <Tooltip title="全屏">
        <Button size="small" type="text" icon={<FullscreenOutlined />} onClick={handleFullscreen} />
      </Tooltip>
      {(onExportJson || onExportPng) && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              ...(onExportJson ? [{ key: 'json', label: '导出 JSON（Coze IR）' }] : []),
              { key: 'png-full', label: '导出 PNG（全部）', disabled: exportingPng },
              { key: 'png-viewport', label: '导出 PNG（当前视口）', disabled: exportingPng },
            ],
            onClick: ({ key }) => {
              if (key === 'json') onExportJson?.()
              else if (key === 'png-full') onExportPng?.('full')
              else if (key === 'png-viewport') onExportPng?.('viewport')
            },
          }}
        >
          <Button size="small" type="text" icon={<DownloadOutlined />} loading={exportingPng}>
            导出
          </Button>
        </Dropdown>
      )}

      <div style={{ width: 1, height: 18, background: CANVAS_TOKENS.border, margin: '0 8px' }} />

      <Button
        size="small"
        icon={<PlusOutlined />}
        onClick={onAddNode}
        style={{
          background: CANVAS_TOKENS.accentSoft,
          color: CANVAS_TOKENS.accentText,
          borderColor: CANVAS_TOKENS.accentSoft,
          fontWeight: 500,
        }}
      >
        添加节点
      </Button>

      <div style={{ width: 1, height: 18, background: CANVAS_TOKENS.border, margin: '0 8px' }} />

      <Button
        size="small"
        type="primary"
        icon={<CaretRightOutlined />}
        loading={running}
        onClick={onRun}
        style={{
          background: CANVAS_TOKENS.run,
          borderColor: CANVAS_TOKENS.run,
          fontWeight: 500,
        }}
      >
        试运行
      </Button>
    </div>
  )
}
