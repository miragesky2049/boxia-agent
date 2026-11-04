import { ClockCircleOutlined } from '@ant-design/icons'

export function NoticeCard({
  text,
  tone = 'waiting',
}: {
  text: string
  tone?: 'waiting' | 'muted'
}) {
  if (tone === 'muted') {
    return <div className="lc-notice lc-notice--muted">{text}</div>
  }
  return (
    <div className="lc-notice">
      <ClockCircleOutlined className="lc-notice__icon" />
      <span>{text}</span>
    </div>
  )
}
