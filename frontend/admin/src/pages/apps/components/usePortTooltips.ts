import { useEffect } from 'react';

// 端口 tooltip（U-S4）：通过 MutationObserver 给 FlowGram 端口 DOM 自动加 title
// FlowGram 端口元素通常带有 data-port-id / port-type 属性
export function usePortTooltips() {
  useEffect(() => {
    const root = document.querySelector('.gedit-playground-container');
    if (!root) return;

    const applyTitles = () => {
      const ports = root.querySelectorAll<HTMLElement>('[class*="port"], [data-port-id]');
      ports.forEach((port) => {
        if (port.dataset.tooltipApplied) return;
        const portId = port.getAttribute('data-port-id') || '';
        const portType = port.classList.contains('input') ? '输入' : '输出';
        if (portId) {
          port.title = `${portType}端口: ${portId}`;
          port.dataset.tooltipApplied = '1';
        }
      });
    };

    applyTitles();
    const observer = new MutationObserver(applyTitles);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
}
