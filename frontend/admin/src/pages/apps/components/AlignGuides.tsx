import { useEffect, useRef } from 'react';
import { CANVAS_TOKENS } from '../canvas/tokens';

// U-N4 对齐辅助线：轻量实现，不依赖 FlowGram 内部 API
// 原理：监听 mousedown/mousemove/mouseup，拖拽节点时读取所有节点 DOM rect，
// 找 ±4px 内的最近锚点，画 1px 蓝紫对齐线；mouseup 时隐藏。
const SNAP_THRESHOLD = 4;
const LINE_COLOR = CANVAS_TOKENS.guide;
// 节点 id 形如 llm-xxx-1 / start-xxx-0 / comment-xxx-2 / if_else-xxx-3
const NODE_ID_RE = /^[a-z][a-z_]*-[A-Za-z0-9]+-/;

function isNodeEl(el: HTMLElement | null): boolean {
  return !!el && NODE_ID_RE.test(el.id);
}

export function AlignGuides() {
  const verticalRef = useRef<HTMLDivElement>(null);
  const horizontalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let draggingId: string | null = null;

    const hide = () => {
      if (verticalRef.current) verticalRef.current.style.opacity = '0';
      if (horizontalRef.current) horizontalRef.current.style.opacity = '0';
    };

    const onMouseDown = (e: MouseEvent) => {
      const playground = document.querySelector('.gedit-playground-container') as HTMLElement | null;
      if (!playground) return;
      let target = e.target as HTMLElement | null;
      while (target && target !== playground) {
        if (isNodeEl(target)) {
          draggingId = target.id;
          break;
        }
        target = target.parentElement;
      }
    };

    const onMouseMove = (_e: MouseEvent) => {
      if (!draggingId) return;
      const playground = document.querySelector('.gedit-playground-container') as HTMLElement | null;
      if (!playground) return;
      const draggedEl = document.getElementById(draggingId);
      if (!draggedEl) return;
      const pgRect = playground.getBoundingClientRect();
      const draggedRect = draggedEl.getBoundingClientRect();
      if (draggedRect.width === 0) return;

      // 被拖拽节点的三条 x 锚（左/中/右）和三条 y 锚（上/中/下）
      const dragEdgesX = [
        draggedRect.left,
        draggedRect.left + draggedRect.width / 2,
        draggedRect.right,
      ];
      const dragEdgesY = [
        draggedRect.top,
        draggedRect.top + draggedRect.height / 2,
        draggedRect.bottom,
      ];

      // 收集其他节点 DOM（节点被 FlowGram 包了一层，不能用 :scope > [id]）
      const others = Array.from(playground.querySelectorAll<HTMLElement>('[id]'))
        .filter((el) => el.id !== draggingId && isNodeEl(el));

      let bestV: number | null = null;
      let bestVDiff = SNAP_THRESHOLD + 1;
      let bestVRange: { start: number; end: number } = { start: 0, end: 0 };

      let bestH: number | null = null;
      let bestHDiff = SNAP_THRESHOLD + 1;
      let bestHRange: { start: number; end: number } = { start: 0, end: 0 };

      others.forEach((nodeEl) => {
        const r = nodeEl.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        const anchorXs = [r.left, r.left + r.width / 2, r.right];
        const anchorYs = [r.top, r.top + r.height / 2, r.bottom];

        for (const dx of dragEdgesX) {
          for (const ax of anchorXs) {
            const diff = Math.abs(dx - ax);
            if (diff < bestVDiff) {
              bestVDiff = diff;
              bestV = ax;
              bestVRange = { start: r.top, end: r.bottom };
            }
          }
        }
        for (const dy of dragEdgesY) {
          for (const ay of anchorYs) {
            const diff = Math.abs(dy - ay);
            if (diff < bestHDiff) {
              bestHDiff = diff;
              bestH = ay;
              bestHRange = { start: r.left, end: r.right };
            }
          }
        }
      });

      if (bestV != null && verticalRef.current) {
        verticalRef.current.style.opacity = '1';
        verticalRef.current.style.left = `${bestV - pgRect.left}px`;
        verticalRef.current.style.top = `${bestVRange.start - pgRect.top}px`;
        verticalRef.current.style.height = `${bestVRange.end - bestVRange.start}px`;
      } else if (verticalRef.current) {
        verticalRef.current.style.opacity = '0';
      }

      if (bestH != null && horizontalRef.current) {
        horizontalRef.current.style.opacity = '1';
        horizontalRef.current.style.top = `${bestH - pgRect.top}px`;
        horizontalRef.current.style.left = `${bestHRange.start - pgRect.left}px`;
        horizontalRef.current.style.width = `${bestHRange.end - bestHRange.start}px`;
      } else if (horizontalRef.current) {
        horizontalRef.current.style.opacity = '0';
      }
    };

    const onMouseUp = () => {
      draggingId = null;
      hide();
    };

    document.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    return () => {
      document.removeEventListener('mousedown', onMouseDown);
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
  }, []);

  return (
    <>
      <div
        ref={verticalRef}
        style={{
          position: 'absolute',
          width: 1,
          background: LINE_COLOR,
          opacity: 0,
          pointerEvents: 'none',
          zIndex: CANVAS_TOKENS.z.guides,
          transition: 'opacity 0.1s',
        }}
      />
      <div
        ref={horizontalRef}
        style={{
          position: 'absolute',
          height: 1,
          background: LINE_COLOR,
          opacity: 0,
          pointerEvents: 'none',
          zIndex: CANVAS_TOKENS.z.guides,
          transition: 'opacity 0.1s',
        }}
      />
    </>
  );
}
