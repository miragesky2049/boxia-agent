// 空白画布欢迎页：当画布中只有 start 节点时显示引导
export function EmptyCanvasWelcome({ visible }: { visible: boolean }) {
  if (!visible) return null
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        pointerEvents: 'none',
        zIndex: 10,
      }}
    >
      <div style={{ fontSize: 48, marginBottom: 16 }}>🪄</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: '#374151', marginBottom: 8 }}>
        从左侧拖入节点，开始搭建你的工作流
      </div>
      <div style={{ fontSize: 13, color: '#9ca3af' }}>
        点击左侧节点库中的节点即可添加到画布，拖拽端口即可连线
      </div>
    </div>
  )
}
