import { useMemo } from 'react';

interface MiniMapProps {
  nodes: Array<{ id: string; x: number; y: number; w?: number; h?: number; color?: string }>;
  viewport?: { x: number; y: number; w: number; h: number; zoom: number };
  onNavigate?: (x: number, y: number) => void;
}

// 简化版小地图（U-B3）：右下角显示节点缩略图，点击可导航
const MAP_WIDTH = 160;
const MAP_HEIGHT = 100;

export function MiniMap({ nodes, viewport, onNavigate }: MiniMapProps) {
  const { scaleX, scaleY, offsetX, offsetY } = useMemo(() => {
    if (nodes.length === 0) {
      return { scaleX: 1, scaleY: 1, offsetX: 0, offsetY: 0 };
    }
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
    const maxX = Math.max(...xs) + 220;
    const maxY = Math.max(...ys) + 60;
    const w = maxX - minX || 1;
    const h = maxY - minY || 1;
    return {
      scaleX: MAP_WIDTH / w,
      scaleY: MAP_HEIGHT / h,
      offsetX: -minX,
      offsetY: -minY,
    };
  }, [nodes]);

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!onNavigate) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / scaleX - offsetX;
    const my = (e.clientY - rect.top) / scaleY - offsetY;
    onNavigate(mx, my);
  };

  return (
    <div
      onClick={handleClick}
      style={{
        position: 'absolute',
        right: 16,
        bottom: 16,
        width: MAP_WIDTH,
        height: MAP_HEIGHT,
        background: 'rgba(255,255,255,0.9)',
        borderRadius: 6,
        border: '1px solid #e5e7eb',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        overflow: 'hidden',
        zIndex: 100,
        cursor: 'pointer',
      }}
    >
      {nodes.map((n) => (
        <div
          key={n.id}
          style={{
            position: 'absolute',
            left: (n.x + offsetX) * scaleX,
            top: (n.y + offsetY) * scaleY,
            width: (n.w || 220) * scaleX,
            height: (n.h || 52) * scaleY,
            background: n.color || '#6366f1',
            borderRadius: 2,
            opacity: 0.7,
          }}
        />
      ))}
      {viewport && (
        <div
          style={{
            position: 'absolute',
            left: (viewport.x + offsetX) * scaleX,
            top: (viewport.y + offsetY) * scaleY,
            width: viewport.w * scaleX * viewport.zoom,
            height: viewport.h * scaleY * viewport.zoom,
            border: '1.5px solid #6366f1',
            borderRadius: 2,
            background: 'rgba(99,102,241,0.1)',
          }}
        />
      )}
    </div>
  );
}
