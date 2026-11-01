import { Button, Tooltip } from 'antd';
import {
  ZoomInOutlined, ZoomOutOutlined, CompressOutlined, FullscreenOutlined,
  PlusOutlined, CaretRightOutlined,
} from '@ant-design/icons';
import type { FreeLayoutPluginContext } from '@flowgram.ai/free-layout-editor';

interface CanvasToolbarProps {
  ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>;
  zoom: number;
  onAddNode: () => void;
  onRun: () => void;
  running?: boolean;
}

// 画布底部居中浮条（V3，对齐 Coze）：缩放 / 适应 / 全屏 | +添加节点 | 试运行
export function CanvasToolbar({ ctxRef, zoom, onAddNode, onRun, running }: CanvasToolbarProps) {
  const handleZoom = (delta: number) => {
    const ctx = ctxRef.current as any;
    // 画布缩放服务挂在 playground.config 上，不是 ctx.viewport
    const config = ctx?.playground?.config;
    if (!config) return;
    const next = Math.max(0.25, Math.min(2, (config.zoom ?? 1) + delta));
    config.updateZoom?.(next, true);
  };

  const handleFit = () => {
    const ctx = ctxRef.current as any;
    ctx?.document?.fitView?.(true);
  };

  const handleFullscreen = () => {
    const el = document.querySelector('.gedit-playground-container') as HTMLElement | null;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen?.();
    } else {
      el.requestFullscreen?.();
    }
  };

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
        border: '1px solid #e5e7eb',
      }}
    >
      <Tooltip title="缩小">
        <Button size="small" type="text" icon={<ZoomOutOutlined />} onClick={() => handleZoom(-0.1)} />
      </Tooltip>
      <span style={{ fontSize: 12, color: '#6b7280', minWidth: 40, textAlign: 'center' }}>
        {Math.round(zoom * 100)}%
      </span>
      <Tooltip title="放大">
        <Button size="small" type="text" icon={<ZoomInOutlined />} onClick={() => handleZoom(0.1)} />
      </Tooltip>
      <Tooltip title="适应视图">
        <Button size="small" type="text" icon={<CompressOutlined />} onClick={handleFit} />
      </Tooltip>
      <Tooltip title="全屏">
        <Button size="small" type="text" icon={<FullscreenOutlined />} onClick={handleFullscreen} />
      </Tooltip>

      <div style={{ width: 1, height: 18, background: '#e5e7eb', margin: '0 8px' }} />

      <Button
        size="small"
        icon={<PlusOutlined />}
        onClick={onAddNode}
        style={{
          background: '#eef2ff', color: '#4f46e5', borderColor: '#eef2ff',
          fontWeight: 500,
        }}
      >
        添加节点
      </Button>

      <div style={{ width: 1, height: 18, background: '#e5e7eb', margin: '0 8px' }} />

      <Button
        size="small"
        type="primary"
        icon={<CaretRightOutlined />}
        loading={running}
        onClick={onRun}
        style={{
          background: '#10b981', borderColor: '#10b981',
          fontWeight: 500,
        }}
      >
        试运行
      </Button>
    </div>
  );
}
