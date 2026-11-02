import '@testing-library/jest-dom/vitest'

// rc-util/antd 会带伪元素参数调用 getComputedStyle，jsdom 对该重载未实现并打印错误；
// 测试里不需要伪元素样式，直接忽略第二个参数。
const originalGetComputedStyle = window.getComputedStyle.bind(window)
window.getComputedStyle = ((element: Element) =>
  originalGetComputedStyle(element)) as typeof window.getComputedStyle

if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as MediaQueryList
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
}

// lottie-web 在模块加载阶段就会创建 canvas 并读取 2d context，
// jsdom 默认不实现 getContext，会导致引用 lottie 的测试文件直接加载失败。
if (typeof HTMLCanvasElement !== 'undefined') {
  const createContextStub = (canvas: HTMLCanvasElement) => {
    const state: Record<string, unknown> = {}
    return new Proxy(state, {
      get(target, prop) {
        if (prop === 'canvas') return canvas
        if (prop in target) return target[prop as string]
        if (prop === 'measureText') return () => ({ width: 0 })
        if (prop === 'getImageData') return () => ({ data: new Uint8ClampedArray(4) })
        if (prop === 'getLineDash') return () => []
        if (prop === 'getContextAttributes') return () => ({})
        if (prop === 'createLinearGradient' || prop === 'createRadialGradient') {
          return () => ({ addColorStop: () => undefined })
        }
        return () => undefined
      },
      set(target, prop, value) {
        target[prop as string] = value
        return true
      },
    })
  }

  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    value(this: HTMLCanvasElement) {
      return createContextStub(this)
    },
  })
}
