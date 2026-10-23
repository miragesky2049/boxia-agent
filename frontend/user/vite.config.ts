import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      port: 5174,
      strictPort: true,
      // 允许 *.localhost，便于本地验证真实子域名解析
      allowedHosts: ['.localhost'],
      proxy: {
        '/api': {
          target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8001',
          // 透传原始 Host，后端据此解析租户子域名
          changeOrigin: false,
        },
      },
    },
  }
})
