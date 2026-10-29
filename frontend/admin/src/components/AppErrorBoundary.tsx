import { Button, Result, Typography } from 'antd'
import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class AppErrorBoundary extends Component<Props, State> {
  override state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('界面渲染异常', error, info.componentStack)
  }

  override render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <Result
        status="error"
        title="页面出错了"
        subTitle="已记录异常信息，请刷新页面重试。若问题持续出现，请联系管理员。"
        extra={[
          <Button key="reload" type="primary" onClick={() => window.location.reload()}>
            刷新页面
          </Button>,
          <Button key="home" onClick={() => window.location.assign('/apps')}>
            返回首页
          </Button>,
        ]}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          错误信息：{error.message}
        </Typography.Paragraph>
      </Result>
    )
  }
}
