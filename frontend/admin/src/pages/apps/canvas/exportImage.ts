import { domToBlob } from 'modern-screenshot'

// 浏览器 canvas 单边上限约 16384px，超出会静默产出空白图
const MAX_CANVAS_SIZE = 16384

export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.click()
  // 下一帧再释放，避免部分浏览器下载被中断
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

// 导出画布 PNG：只截 FlowGram 画布层，浮条/小地图等叠加层不在截取范围内
export async function exportElementAsPng(element: HTMLElement, fileName: string): Promise<void> {
  const scale = Math.min(3, Math.max(2, window.devicePixelRatio || 1))
  const blob = await domToBlob(element, {
    backgroundColor: '#ffffff',
    scale,
    maximumCanvasSize: MAX_CANVAS_SIZE,
  })
  downloadBlob(blob, fileName)
}
