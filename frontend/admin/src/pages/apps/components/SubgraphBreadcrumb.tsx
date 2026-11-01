import { Button } from 'antd';

// 子图面包屑（B6）：展示当前下钻路径，支持回退到任意层级
export function SubgraphBreadcrumb({
  stackDepth,
  breadcrumb,
  onExit,
}: {
  stackDepth: number;
  breadcrumb: Array<{ id: string; title: string }>;
  onExit: (keepDepth: number) => void;
}) {
  if (stackDepth === 0) return null;
  return (
    <div style={{
      position: 'absolute', top: 48, left: 16, zIndex: 100,
      display: 'flex', alignItems: 'center', gap: 8,
      background: '#fff', borderRadius: 8, padding: '6px 12px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.1)', fontSize: 13,
    }}>
      <Button type="link" size="small" onClick={() => onExit(stackDepth)}>
        返回根图
      </Button>
      <span style={{ color: '#ccc' }}>/</span>
      {breadcrumb.map((item, idx) => (
        <span key={item.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          {idx > 0 && <span style={{ color: '#ccc' }}>/</span>}
          {idx === breadcrumb.length - 1 ? (
            <strong>{item.title}</strong>
          ) : (
            <Button type="link" size="small" onClick={() => onExit(stackDepth - idx - 1)}>
              {item.title}
            </Button>
          )}
        </span>
      ))}
    </div>
  );
}
