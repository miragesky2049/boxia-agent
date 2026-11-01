import { useEffect, useRef } from 'react';
import type { FreeLayoutPluginContext } from '@flowgram.ai/free-layout-editor';
import { CANVAS_TOKENS } from '../canvas/tokens';
import { getSelection, getZoom, subscribeViewport } from '../canvas/adapters/flowgramContext';

// U-N4 对齐辅助线（N9-12）：只显示、不吸附，不改任何节点坐标。
// 拖拽开始时缓存其他节点 rect，拖动中只重算被拖节点，rAF 节流。
const THRESHOLD_WORLD_PX = 4;
const MIN_THRESHOLD_PX = 3;
const GUIDE_EXTEND_PX = 12;

interface NodeRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface AlignGuidesProps {
  ctxRef: React.MutableRefObject<FreeLayoutPluginContext | null>;
}

export function AlignGuides({ ctxRef }: AlignGuidesProps) {
  const verticalRef = useRef<HTMLDivElement>(null);
  const horizontalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let draggingId: string | null = null;
    // 其余节点的 rect 在按下时缓存，拖拽过程中不必重复查询 DOM
    let others: NodeRect[] = [];
    let frame = 0;

    const hide = () => {
      if (frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
      if (verticalRef.current) verticalRef.current.style.opacity = '0';
      if (horizontalRef.current) horizontalRef.current.style.opacity = '0';
    };

    const compare = (a: number, b: number, bestDiff: number) => {
      const diff = Math.abs(a - b);
      return diff < bestDiff ? { value: b, diff } : null;
    };

    const apply = () => {
      frame = 0;
      if (!draggingId) return;
      const playground = document.querySelector<HTMLElement>('.gedit-playground-container');
      if (!playground) {
        hide();
        return;
      }
      const draggedEl = playground.querySelector<HTMLElement>(
        `[data-node-id="${CSS.escape(draggingId)}"]`,
      );
      if (!draggedEl) {
        hide();
        return;
      }
      const draggedRect = draggedEl.getBoundingClientRect();
      if (draggedRect.width === 0) return;

      // 阈值按世界像素换算成屏幕像素，各缩放档位下手感一致
      const zoom = getZoom(ctxRef.current) || 1;
      const threshold = Math.max(MIN_THRESHOLD_PX, THRESHOLD_WORLD_PX * zoom);

      const dragXs = [draggedRect.left, draggedRect.left + draggedRect.width / 2, draggedRect.right];
      const dragYs = [draggedRect.top, draggedRect.top + draggedRect.height / 2, draggedRect.bottom];

      let bestV: number | null = null;
      let bestVDiff = threshold;
      let vStart = 0;
      let vEnd = 0;
      let bestH: number | null = null;
      let bestHDiff = threshold;
      let hStart = 0;
      let hEnd = 0;

      for (const rect of others) {
        const anchorXs = [rect.left, rect.left + (rect.right - rect.left) / 2, rect.right];
        const anchorYs = [rect.top, rect.top + (rect.bottom - rect.top) / 2, rect.bottom];

        for (const x of dragXs) {
          for (const ax of anchorXs) {
            const hit = compare(x, ax, bestVDiff);
            if (hit) {
              bestV = hit.value;
              bestVDiff = hit.diff;
              vStart = rect.top;
              vEnd = rect.bottom;
            }
          }
        }
        for (const y of dragYs) {
          for (const ay of anchorYs) {
            const hit = compare(y, ay, bestHDiff);
            if (hit) {
              bestH = hit.value;
              bestHDiff = hit.diff;
              hStart = rect.left;
              hEnd = rect.right;
            }
          }
        }
      }

      const pgRect = playground.getBoundingClientRect();

      if (bestV != null && verticalRef.current) {
        const el = verticalRef.current;
        el.style.opacity = '1';
        el.style.left = `${bestV - pgRect.left}px`;
        el.style.top = `${vStart - GUIDE_EXTEND_PX - pgRect.top}px`;
        el.style.height = `${vEnd - vStart + GUIDE_EXTEND_PX * 2}px`;
      } else if (verticalRef.current) {
        verticalRef.current.style.opacity = '0';
      }

      if (bestH != null && horizontalRef.current) {
        const el = horizontalRef.current;
        el.style.opacity = '1';
        el.style.top = `${bestH - pgRect.top}px`;
        el.style.left = `${hStart - GUIDE_EXTEND_PX - pgRect.left}px`;
        el.style.width = `${hEnd - hStart + GUIDE_EXTEND_PX * 2}px`;
      } else if (horizontalRef.current) {
        horizontalRef.current.style.opacity = '0';
      }
    };

    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(apply);
    };

    const onPointerDown = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (target.closest('.boxia-minimap, .ant-drawer, .ant-modal, .ant-popover, .ant-dropdown')) {
        return;
      }
      const nodeEl = target.closest<HTMLElement>('[data-node-id]');
      if (!nodeEl) return;
      const playground = document.querySelector<HTMLElement>('.gedit-playground-container');
      if (!playground || !playground.contains(nodeEl)) return;
      // 空格平移模式在拖画布，不是拖节点
      const cursor = document.body.style.cursor;
      if (cursor === 'grab' || cursor === 'grabbing') return;

      const nodeId = nodeEl.dataset.nodeId || '';
      if (!nodeId) return;
      draggingId = nodeId;

      // 多选拖拽时，同批选中的节点会一起移动，不能作为对齐基准
      const excluded = new Set(getSelection(ctxRef.current).nodeIds);
      excluded.add(nodeId);
      others = Array.from(playground.querySelectorAll<HTMLElement>('[data-node-id]'))
        .filter((el) => !excluded.has(el.dataset.nodeId || ''))
        .map((el) => el.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0)
        .map((rect) => ({
          left: rect.left,
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
        }));
    };

    const onPointerMove = () => {
      if (!draggingId) return;
      schedule();
    };

    const endDrag = () => {
      draggingId = null;
      others = [];
      hide();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') endDrag();
    };

    // 缩放 / 滚动 / 切换子图后参考线立即失效
    const viewportDisposable = subscribeViewport(ctxRef.current, () => {
      if (draggingId) hide();
    });

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', endDrag);
    document.addEventListener('pointercancel', endDrag);
    window.addEventListener('blur', endDrag);
    document.addEventListener('keydown', onKeyDown);

    return () => {
      endDrag();
      viewportDisposable.dispose?.();
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('pointermove', onPointerMove);
      document.removeEventListener('pointerup', endDrag);
      document.removeEventListener('pointercancel', endDrag);
      window.removeEventListener('blur', endDrag);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [ctxRef]);

  const lineBase: React.CSSProperties = {
    position: 'absolute',
    opacity: 0,
    pointerEvents: 'none',
    zIndex: CANVAS_TOKENS.z.guides,
    transition: 'opacity 0.1s',
    backgroundImage: `repeating-linear-gradient(to bottom, ${CANVAS_TOKENS.guide} 0 4px, transparent 4px 8px)`,
  };

  return (
    <>
      <div ref={verticalRef} style={{ ...lineBase, width: 1 }} />
      <div
        ref={horizontalRef}
        style={{
          ...lineBase,
          height: 1,
          backgroundImage: `repeating-linear-gradient(to right, ${CANVAS_TOKENS.guide} 0 4px, transparent 4px 8px)`,
        }}
      />
    </>
  );
}
