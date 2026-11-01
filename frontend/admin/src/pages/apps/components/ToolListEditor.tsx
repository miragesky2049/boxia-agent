import { Button, Input, Space } from 'antd';

export interface ToolItem {
  name: string;
  description: string;
}

// 兼容历史数据：字符串、对象数组、JSON 字符串都归一为 ToolItem[]
function normalizeTools(raw: any): ToolItem[] {
  const toItem = (it: any): ToolItem => {
    if (typeof it === 'string') return { name: it, description: '' };
    return {
      name: String(it?.name ?? it?.tool_name ?? it?.toolName ?? it?.id ?? ''),
      description: String(it?.description ?? it?.desc ?? ''),
    };
  };
  if (Array.isArray(raw)) return raw.map(toItem);
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.map(toItem);
    } catch {
      // 非 JSON 文本按单个工具名处理
      return [{ name: raw.trim(), description: '' }];
    }
  }
  return [];
}

interface ToolListEditorProps {
  value: any;
  onChange: (next: ToolItem[]) => void;
}

export function ToolListEditor({ value, onChange }: ToolListEditorProps) {
  const items = normalizeTools(value);

  const updateItem = (idx: number, patch: Partial<ToolItem>) => {
    onChange(items.map((it, i) => (i === idx ? { ...it, ...patch } : it)));
  };

  const removeItem = (idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    onChange([...items, { name: '', description: '' }]);
  };

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      {items.length === 0 && (
        <div style={{
          padding: '8px 10px', background: '#f9fafb', borderRadius: 6,
          fontSize: 12, color: '#9ca3af',
        }}>
          暂未添加工具，点击下方按钮添加
        </div>
      )}
      {items.map((item, idx) => (
        <div key={idx} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
          <Input
            value={item.name}
            onChange={(e) => updateItem(idx, { name: e.target.value })}
            placeholder="工具名称"
            style={{ width: 140 }}
          />
          <Input
            value={item.description}
            onChange={(e) => updateItem(idx, { description: e.target.value })}
            placeholder="工具描述（可选）"
            style={{ flex: 1 }}
          />
          <Button size="small" danger type="text" onClick={() => removeItem(idx)}>
            删除
          </Button>
        </div>
      ))}
      <Button size="small" onClick={addItem} style={{ width: '100%' }}>
        + 添加工具
      </Button>
    </Space>
  );
}
