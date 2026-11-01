import { Button, Drawer, Space, Tag, Typography } from 'antd';
import type { GraphVersionItem } from '../../../api/apps';

// 版本历史抽屉（B9）：整图版本快照 + 回滚
export function VersionHistoryDrawer({
  open,
  versions,
  onClose,
  onRollback,
}: {
  open: boolean;
  versions: GraphVersionItem[];
  onClose: () => void;
  onRollback: (version: number) => void;
}) {
  return (
    <Drawer
      title="版本历史"
      open={open}
      onClose={onClose}
      width="min(480px, 92vw)"
    >
      {versions.length === 0 ? (
        <Typography.Text type="secondary">暂无历史版本</Typography.Text>
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          {versions.map((v, idx) => (
            <div
              key={v.id}
              style={{
                padding: 12, border: '1px solid #f0f0f0', borderRadius: 8,
                background: idx === 0 ? '#f6ffed' : '#fff',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <Tag color={idx === 0 ? 'green' : 'default'}>v{v.version}</Tag>
                {idx === 0 && <Tag color="blue">当前</Tag>}
                <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto' }}>
                  {new Date(v.created_at).toLocaleString()}
                </Typography.Text>
              </div>
              {v.changelog && (
                <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{v.changelog}</div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {v.created_by && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    by {v.created_by}
                  </Typography.Text>
                )}
                {idx !== 0 && (
                  <Button
                    size="small"
                    danger
                    style={{ marginLeft: 'auto' }}
                    onClick={() => onRollback(v.version)}
                  >
                    回滚到此版本
                  </Button>
                )}
              </div>
            </div>
          ))}
        </Space>
      )}
    </Drawer>
  );
}
