import { useEffect } from 'react';

// 端口 tooltip（U-S4）：通过 MutationObserver 给 FlowGram 端口 DOM 自动加 title
// FlowGram 端口 DOM：data-port-entity-id="port_{input|output}_{node.id}_{portID}"
// 端口真实 DOM 属性是 data-port-entity-id / data-port-entity-type，不是 data-port-id。
const PORT_TYPE_LABELS: Record<string, string> = {
  input: '输入',
  output: '输出',
};

export function usePortTooltips() {
  useEffect(() => {
    const root = document.querySelector('.gedit-playground-container');
    if (!root) return;

    // 端口实体 id 内嵌 node.id，借最近的节点 DOM（id=node.id）截出 portID
    const resolvePortId = (port: HTMLElement, portType: string): string => {
      const entityId = port.getAttribute('data-port-entity-id') || '';
      let el: HTMLElement | null = port.parentElement;
      while (el && el !== root) {
        if (el.id) {
          const prefix = `port_${portType}_${el.id}_`;
          return entityId.startsWith(prefix) ? entityId.slice(prefix.length) : '';
        }
        el = el.parentElement;
      }
      return '';
    };

    const applyTitles = () => {
      const ports = root.querySelectorAll<HTMLElement>('[data-port-entity-id]');
      ports.forEach((port) => {
        if (port.dataset.tooltipApplied) return;
        const portType = port.getAttribute('data-port-entity-type') || '';
        const portId = resolvePortId(port, portType);
        if (!portId) return;
        const typeLabel = PORT_TYPE_LABELS[portType] || '端口';
        port.title = `${typeLabel}端口: ${portId}`;
        port.dataset.tooltipApplied = '1';
      });
    };

    applyTitles();
    const observer = new MutationObserver(applyTitles);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
}
