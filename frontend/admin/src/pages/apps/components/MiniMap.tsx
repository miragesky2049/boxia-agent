import { useMemo } from 'react';

interface MiniMapNode {
  id: string;
  x: number;
  y: number;
  w?: number;
  h?: number;
  color?: string;
}

interface MiniMapViewport {
  x: number;
  y: number;
  w: number;
  h: number;
  zoom?: number;
}

interface MiniMapProps {
  nodes: MiniMapNode[];
  viewport?: MiniMapViewport | null;
  onNavigate?: (x: number, y: number) => void;
}

// 右下角小地图（对齐 Coze）：等比例缩略整张画布，叠加当前可视区域框，点击可导航
const MAP_WIDTH = 160;
const MAP_HEIGHT = 100;
const MAP_PADDING = 8;
const DEFAULT_NODE_W = 220;
const DEFAULT_NODE_H = 52;

export function MiniMap({ nodes, viewport, onNavigate }: MiniMapProps) {
  // 以节点包围盒缩放并居中（节点在图里占比更大、更易点击）；
  // 空画布时退化为可视区域包围盒
  const layout = useMemo(() => {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const node of nodes) {
      const w = node.w ?? DEFAULT_NODE_W;
      const h = node.h ?? DEFAULT_NODE_H;
      minX = Math.min(minX, node.x);
      minY = Math.min(minY, node.y);
      maxX = Math.max(maxX, node.x + w);
      maxY = Math.max(maxY, node.y + h);
    }

    if (!Number.isFinite(minX) && viewport && viewport.w > 0 && viewport.h > 0) {
      minX = viewport.x;
      minY = viewport.y;
      maxX = viewport.x + viewport.w;
      maxY = viewport.y + viewport.h;
    }

    if (!Number.isFinite(minX)) {
      return { scale: 1, offsetX: 0, offsetY: 0 };
    }

    const contentW = Math.max(maxX - minX, 1);
    const contentH = Math.max(maxY - minY, 1);
    const scale = Math.min(
      (MAP_WIDTH - MAP_PADDING * 2) / contentW,
      (MAP_HEIGHT - MAP_PADDING * 2) / contentH,
    );
    return {
      scale,
      offsetX: (MAP_WIDTH - contentW * scale) / 2 - minX * scale,
      offsetY: (MAP_HEIGHT - contentH * scale) / 2 - minY * scale,
    };
  }, [nodes, viewport]);

  const { scale, offsetX, offsetY } = layout;

  // 相机框可能比节点包围盒大很多，裁剪到小地图边界内，避免只露出一条边
  const viewportFrame = useMemo(() => {
    if (!viewport || viewport.w <= 0 || viewport.h <= 0) return null;
    const clamp = (v: number, max: number) => Math.max(0, Math.min(max, v));
    const left = clamp(viewport.x * scale + offsetX, MAP_WIDTH);
    const top = clamp(viewport.y * scale + offsetY, MAP_HEIGHT);
    const right = clamp((viewport.x + viewport.w) * scale + offsetX, MAP_WIDTH);
    const bottom = clamp((viewport.y + viewport.h) * scale + offsetY, MAP_HEIGHT);
    const width = Math.max(right - left, 4);
    const height = Math.max(bottom - top, 4);
    // 相机已覆盖全部内容时（如首次 fitView 且未放大），不再画框，否则整块地图像被染色
    const coversAll = left <= 0 && top <= 0 && width >= MAP_WIDTH - 1 && height >= MAP_HEIGHT - 1;
    return coversAll ? null : { left, top, width, height };
  }, [viewport, scale, offsetX, offsetY]);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!onNavigate) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const canvasX = (e.clientX - rect.left - offsetX) / scale;
    const canvasY = (e.clientY - rect.top - offsetY) / scale;
    onNavigate(canvasX, canvasY);
  };

  return (
    <div
      className="boxia-minimap"
      onClick={handleClick}
      style={{
        position: 'absolute',
        right: 16,
        bottom: 16,
        width: MAP_WIDTH,
        height: MAP_HEIGHT,
        background: 'rgba(255,255,255,0.95)',
        borderRadius: 6,
        border: '1px solid #e5e7eb',
        boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
        overflow: 'hidden',
        zIndex: 100,
        cursor: 'pointer',
      }}
    >
      {nodes.map((node) => (
        <div
          key={node.id}
          style={{
            position: 'absolute',
            left: node.x * scale + offsetX,
            top: node.y * scale + offsetY,
            width: Math.max((node.w ?? DEFAULT_NODE_W) * scale, 2),
            height: Math.max((node.h ?? DEFAULT_NODE_H) * scale, 2),
            background: node.color || '#6366f1',
            borderRadius: 2,
            opacity: 0.85,
          }}
        />
      ))}
      {viewportFrame && (
        <div
          style={{
            position: 'absolute',
            left: viewportFrame.left,
            top: viewportFrame.top,
            width: viewportFrame.width,
            height: viewportFrame.height,
            border: '1.5px solid rgba(99,102,241,0.9)',
            borderRadius: 2,
            background: 'rgba(99,102,241,0.08)',
            boxShadow: '0 0 0 1px rgba(255,255,255,0.6)',
            pointerEvents: 'none',
          }}
        />
      )}
    </div>
  );
}
