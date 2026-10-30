import { Button, Typography } from '@douyinfe/semi-ui';
import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class AppErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('界面渲染异常', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Typography.Title heading={3}>页面出错了</Typography.Title>
        <Typography.Paragraph type="secondary">
          已记录异常信息，请刷新页面重试。若问题持续出现，请联系管理员。
        </Typography.Paragraph>
        <Typography.Paragraph type="tertiary">错误信息：{error.message}</Typography.Paragraph>
        <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'center' }}>
          <Button type="primary" onClick={() => window.location.reload()}>
            刷新页面
          </Button>
          <Button onClick={() => window.location.assign('/apps')}>返回首页</Button>
        </div>
      </div>
    );
  }
}
