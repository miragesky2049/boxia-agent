import { Drawer, Tree, Tag, Empty } from 'antd';
import { useMemo } from 'react';
import type { NodeMeta } from '../../../api/nodeMeta';

interface VariablesDrawerProps {
  open: boolean;
  onClose: () => void;
  nodes: Array<{
    id: string;
    typeKey: string;
    title: string;
    config?: Record<string, any>;
  }>;
  keyToMeta: Record<string, NodeMeta>;
}

// 变量抽屉（U-L2）：展示当前画布所有节点的输出变量，方便引用
export function VariablesDrawer({ open, onClose, nodes, keyToMeta }: VariablesDrawerProps) {
  const treeData = useMemo(() => {
    if (nodes.length === 0) return [];
    return nodes.map((node) => {
      const meta = keyToMeta[node.typeKey];
      const outputs = (meta?.outputs || []).map((p) => ({
        key: `${node.id}.output.${p.name}`,
        title: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <code style={{ fontSize: 11, background: '#f3f4f6', padding: '0 4px', borderRadius: 3 }}>
              {p.name}
            </code>
            <span style={{ color: '#9ca3af', fontSize: 11 }}>{p.label || ''}</span>
          </span>
        ),
        isLeaf: true,
      }));
      // START 节点的入参作为虚拟输出
      const startInputs =
        node.typeKey === 'start' && Array.isArray(node.config?.inputs)
          ? (node.config.inputs as Array<{ name: string; type?: string }>).map((inp) => ({
              key: `${node.id}.output.${inp.name}`,
              title: (
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>入参</Tag>
                  <code style={{ fontSize: 11, background: '#f3f4f6', padding: '0 4px', borderRadius: 3 }}>
                    {inp.name}
                  </code>
                </span>
              ),
              isLeaf: true,
            }))
          : [];
      return {
        key: node.id,
        title: (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontWeight: 500 }}>{node.title || meta?.title || node.id}</span>
            <Tag style={{ fontSize: 10, margin: 0 }} color={meta?.color || 'default'}>
              {node.typeKey}
            </Tag>
          </span>
        ),
        children: [...outputs, ...startInputs],
      };
    });
  }, [nodes, keyToMeta]);

  return (
    <Drawer
      title="变量引用"
      open={open}
      onClose={onClose}
      width="min(360px, 92vw)"
      placement="right"
    >
      <div style={{ marginBottom: 12, fontSize: 12, color: '#9ca3af' }}>
        点击字段可复制引用表达式 <code style={{ background: '#f3f4f6', padding: '0 4px', borderRadius: 3 }}>{'{{节点ID.output.字段名}}'}</code>
      </div>
      {treeData.length === 0 ? (
        <Empty description="画布中暂无节点" />
      ) : (
        <Tree
          treeData={treeData as any}
          defaultExpandAll
          onSelect={(keys) => {
            const key = keys[0];
            if (typeof key === 'string' && key.includes('.output.')) {
              const ref = `{{${key}}}`;
              navigator.clipboard?.writeText(ref).catch(() => {});
            }
          }}
        />
      )}
    </Drawer>
  );
}
