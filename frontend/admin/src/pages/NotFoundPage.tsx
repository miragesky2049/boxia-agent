import { Button, Result } from 'antd'
import { useNavigate } from 'react-router-dom'

export default function NotFoundPage() {
  const navigate = useNavigate()

  return (
    <Result
      status="404"
      title="404"
      subTitle="页面不存在或已被移除。"
      extra={
        <Button type="primary" onClick={() => navigate('/apps', { replace: true })}>
          返回智能体管理
        </Button>
      }
    />
  )
}
