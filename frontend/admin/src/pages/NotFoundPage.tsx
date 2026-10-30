import { Button, Typography } from '@douyinfe/semi-ui';
import { useNavigate } from 'react-router-dom';

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div style={{ padding: 48, textAlign: 'center' }}>
      <Typography.Title heading={3}>404</Typography.Title>
      <Typography.Paragraph type="secondary">页面不存在或已被移除。</Typography.Paragraph>
      <Button type="primary" onClick={() => navigate('/apps', { replace: true })}>
        返回智能体管理
      </Button>
    </div>
  );
}
