import { getScroll, setScroll, type FlowContext } from './flowgramContext';

// T9-07：对齐 Coze —— 空白处普通左键拖拽平移（Shift+拖拽由 selectBox 负责框选）。
// FlowGram 的选区插件在 canSelect 返回 false 时不会开始框选，也不会平移，需要自绘。
export function setupCanvasPan(ctx: FlowContext): () => void {
  if (!ctx) return () => undefined;

  // 命中这些元素时不启动平移，避免抢走节点/端口/连线/浮层的既有交互
  const interactiveSelector = [
    '[data-node-id]',
    '[data-port-entity-id]',
    '.gedit-flow-activity-edge',
    '.boxia-minimap',
    '.ant-popover',
    '.ant-drawer',
    '.ant-dropdown',
    'button',
    'input',
    'textarea',
    'select',
    'a',
  ].join(',');

  // 空格按住时进入平移模式：指针落在节点上也平移，而不是拖动节点（N9-04）
  const overlaySelector = '.boxia-minimap, .ant-popover, .ant-dropdown, .ant-drawer, .ant-modal';
  const typingSelector = 'input, textarea, select, button, [contenteditable="true"]';

  let panning = false;
  let spaceDown = false;
  let startX = 0;
  let startY = 0;
  let originScrollX = 0;
  let originScrollY = 0;

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.code !== 'Space' || spaceDown) return;
    const target = e.target as HTMLElement | null;
    if (!target || target.closest(typingSelector)) return;
    if (!document.querySelector('.gedit-playground-container')) return;
    spaceDown = true;
    document.body.style.cursor = 'grab';
    // 阻止空格默认的页面滚动
    e.preventDefault();
  };

  const onKeyUp = (e: KeyboardEvent) => {
    if (e.code !== 'Space') return;
    spaceDown = false;
    if (!panning) document.body.style.cursor = '';
  };

  const onWindowBlur = () => {
    spaceDown = false;
    if (!panning) document.body.style.cursor = '';
  };

  // 用捕获阶段挂在 document 上：FlowGram 的拖拽层会 stopPropagation，冒泡阶段收不到
  const onPointerDown = (e: PointerEvent) => {
    if (e.button !== 0 || e.shiftKey) return;
    const target = e.target as HTMLElement | null;
    if (!target || !target.closest('.gedit-playground-container')) return;
    if (target.closest(overlaySelector)) return;
    if (spaceDown) {
      // 截断 FlowGram 的节点拖拽，本次指针序列只用于平移
      e.preventDefault();
      e.stopPropagation();
    } else if (target.closest(interactiveSelector)) {
      return;
    }
    panning = true;
    startX = e.clientX;
    startY = e.clientY;
    const origin = getScroll(ctx);
    originScrollX = origin.x;
    originScrollY = origin.y;
    document.body.style.cursor = 'grabbing';
  };

  const onPointerMove = (e: PointerEvent) => {
    if (!panning) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    // scrollX/Y 是画布层的屏幕平移量，与鼠标位移 1:1
    setScroll(ctx, originScrollX + dx, originScrollY + dy);
  };

  const onPointerUp = () => {
    if (!panning) return;
    panning = false;
    document.body.style.cursor = spaceDown ? 'grab' : '';
  };

  document.addEventListener('pointerdown', onPointerDown, true);
  document.addEventListener('pointermove', onPointerMove, true);
  document.addEventListener('pointerup', onPointerUp, true);
  document.addEventListener('keydown', onKeyDown, true);
  document.addEventListener('keyup', onKeyUp, true);
  window.addEventListener('blur', onWindowBlur);
  return () => {
    panning = false;
    spaceDown = false;
    document.body.style.cursor = '';
    document.removeEventListener('pointerdown', onPointerDown, true);
    document.removeEventListener('pointermove', onPointerMove, true);
    document.removeEventListener('pointerup', onPointerUp, true);
    document.removeEventListener('keydown', onKeyDown, true);
    document.removeEventListener('keyup', onKeyUp, true);
    window.removeEventListener('blur', onWindowBlur);
  };
}
