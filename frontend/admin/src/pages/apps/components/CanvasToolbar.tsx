import { Button, Tooltip } from 'antd';
import { ZoomInOutlined, ZoomOutOutlined, CompressOutlined, FullscreenOutlined } from '@ant-design/icons';
import type { FreeLayoutPluginContext } from '@flowgram.ai/free-layout-editor';

interface CanvasToolbarProps {
  ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>;
  zoom: number;
}

// 画布顶部居中悬浮工具栏（与 Coze 对齐）：缩放 + 适应视图 + 全屏
export function CanvasToolbar({ ctxRef, zoom }: CanvasToolbarProps) {
  const handleZoom = (delta: number) => {
    const ctx = ctxRef.current as any;
    if (!ctx?.viewport) return;
    const next = Math.max(0.25, Math.min(2, (ctx.viewport.zoom ?? 1) + delta));
    ctx.viewport.zoomTo?.(next);
  };

  const handleFit = () => {
    const ctx = ctxRef.current as any;
    ctx?.viewport?.fitView?.();
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
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        gap: 4,
        padding: '4px 8px',
        background: '#fff',
        borderRadius: 8,
        boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
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
      <div style={{ width: 1, height: 16, background: '#e5e7eb', margin: '0 4px' }} />
      <Tooltip title="适应视图">
        <Button size="small" type="text" icon={<CompressOutlined />} onClick={handleFit} />
      </Tooltip>
      <Tooltip title="全屏">
        <Button size="small" type="text" icon={<FullscreenOutlined />} onClick={handleFullscreen} />
      </Tooltip>
    </div>
  );
}
