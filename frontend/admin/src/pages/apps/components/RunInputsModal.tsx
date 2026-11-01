import { Button, Input, Modal, Space, Tag, Typography, Upload } from 'antd';
import type { UploadFile } from 'antd';

// 试运行入参弹窗（B7 + T18 多模态）：image/file 类型走上传并转 dataURL
export function RunInputsModal({
  open,
  params,
  values,
  onChange,
  onCancel,
  onOk,
}: {
  open: boolean;
  params: Array<{ name: string; type?: string }>;
  values: Record<string, any>;
  onChange: (patch: Record<string, any>) => void;
  onCancel: () => void;
  onOk: () => void;
}) {
  return (
    <Modal
      title="试运行入参"
      open={open}
      onCancel={onCancel}
      onOk={onOk}
      okText="开始运行"
      cancelText="取消"
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {params.map((p) => {
          const type = (p.type || 'string').toLowerCase();
          const isImageOrFile = type === 'image' || type === 'file';
          if (!isImageOrFile) {
            return (
              <div key={p.name}>
                <Typography.Text type="secondary">{p.name}</Typography.Text>
                <Input
                  value={values[p.name] ?? ''}
                  onChange={(e) => onChange({ [p.name]: e.target.value })}
                  placeholder={p.type || 'string'}
                />
              </div>
            );
          }
          // T18：文件读为 dataURL，多图用逗号分隔
          const currentValue = (values[p.name] as string) || '';
          const currentUrls = currentValue ? currentValue.split(',').filter(Boolean) : [];
          return (
            <div key={p.name}>
              <Typography.Text type="secondary">
                {p.name}
                <Tag color="purple" style={{ marginLeft: 8 }}>{p.type}</Tag>
              </Typography.Text>
              <Upload
                accept={type === 'image' ? 'image/*' : undefined}
                listType="picture"
                multiple
                beforeUpload={(file) => {
                  const reader = new FileReader();
                  reader.onload = () => {
                    const dataUrl = String(reader.result || '');
                    const prevVal = (values[p.name] as string) || '';
                    const urls = prevVal ? prevVal.split(',').filter(Boolean) : [];
                    urls.push(dataUrl);
                    onChange({ [p.name]: urls.join(',') });
                  };
                  reader.readAsDataURL(file);
                  return false; // 阻止自动上传
                }}
                onRemove={() => {
                  // 简化：onRemove 无法精确匹配 dataURL，这里改为清空当前字段让用户重选
                  onChange({ [p.name]: '' });
                  return true;
                }}
                fileList={currentUrls.map((url, idx) => ({
                  uid: String(idx),
                  name: `upload-${idx + 1}`,
                  status: 'done' as const,
                  url,
                })) as UploadFile[]}
              >
                <Button>上传{type === 'image' ? '图片' : '文件'}</Button>
              </Upload>
            </div>
          );
        })}
      </Space>
    </Modal>
  );
}
