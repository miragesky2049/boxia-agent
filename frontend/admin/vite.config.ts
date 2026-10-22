import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      // 允许 *.localhost，便于本地验证真实子域名解析
      allowedHosts: ['.localhost'],
      proxy: {
        '/api': {
          target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
          // 透传原始 Host，后端据此解析 adminsystem.localhost / acme.localhost
          changeOrigin: false,
        },
      },
    },
    build: {
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined
            if (
              id.includes('/react/') ||
              id.includes('/react-dom/') ||
              id.includes('react-router')
            ) {
              return 'react'
            }
            if (id.includes('antd') || id.includes('@ant-design')) {
              return 'antd'
            }
            return undefined
          },
        },
      },
    },
  }
})
