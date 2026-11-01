import { Input, Select, Checkbox, Button } from 'antd';
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';

export interface ParameterItem {
  name: string;
  type: string;
  required: boolean;
  description?: string;
}

const TYPE_OPTIONS = [
  { value: 'string', label: 'String' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'file', label: 'File' },
  { value: 'image', label: 'Image' },
  { value: 'array[string]', label: 'Array[String]' },
  { value: 'array[number]', label: 'Array[Number]' },
  { value: 'array[object]', label: 'Array[Object]' },
];

function parseValue(raw: any): ParameterItem[] {
  if (Array.isArray(raw)) {
    return raw.map((item: any, idx: number) => ({
      name: String(item?.name ?? item?.variableName ?? `param_${idx + 1}`),
      type: String(item?.type ?? item?.variableType ?? 'string'),
      required: Boolean(item?.required),
      description: item?.description ? String(item.description) : undefined,
    }));
  }
  return [];
}

interface ParameterListEditorProps {
  value: any;
  onChange: (next: ParameterItem[]) => void;
}

// 对齐 Coze START 节点入参表格编辑器：变量名 + 类型下拉 + 必填 + 引用 + 删除
export function ParameterListEditor({ value, onChange }: ParameterListEditorProps) {
  const items = parseValue(value);

  const updateItem = (idx: number, patch: Partial<ParameterItem>) => {
    const next = items.map((it, i) => (i === idx ? { ...it, ...patch } : it));
    onChange(next);
  };

  const removeItem = (idx: number) => {
    onChange(items.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    onChange([...items, { name: `param_${items.length + 1}`, type: 'string', required: false }]);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* 表头 */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 120px 60px 40px',
          gap: 8,
          fontSize: 12,
          color: '#9ca3af',
          padding: '0 4px',
        }}
      >
        <span>变量名</span>
        <span>变量类型</span>
        <span>必填</span>
        <span></span>
      </div>

      {/* 参数行 */}
      {items.length === 0 && (
        <div style={{ fontSize: 12, color: '#9ca3af', padding: '8px 4px' }}>
          暂无参数，点击下方按钮添加
        </div>
      )}

      {items.map((item, idx) => (
        <div
          key={idx}
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 120px 60px 40px',
            gap: 8,
            alignItems: 'center',
            background: '#f9fafb',
            borderRadius: 6,
            padding: '6px 8px',
          }}
        >
          <Input
            size="small"
            value={item.name}
            placeholder="参数名"
            onChange={(e) => updateItem(idx, { name: e.target.value })}
          />
          <Select
            size="small"
            value={item.type}
            options={TYPE_OPTIONS}
            onChange={(v) => updateItem(idx, { type: v })}
          />
          <Checkbox
            checked={item.required}
            onChange={(e) => updateItem(idx, { required: e.target.checked })}
          />
          <Button
            size="small"
            type="text"
            danger
            icon={<DeleteOutlined />}
            onClick={() => removeItem(idx)}
          />
        </div>
      ))}

      {/* 添加按钮 */}
      <Button
        size="small"
        type="dashed"
        icon={<PlusOutlined />}
        onClick={addItem}
        style={{ marginTop: 4 }}
      >
        添加参数
      </Button>
    </div>
  );
}
