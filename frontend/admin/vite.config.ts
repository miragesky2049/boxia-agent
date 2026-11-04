import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const semiUiPkgDir = path.resolve(__dirname, 'node_modules/@douyinfe/semi-ui')
  return {
    plugins: [react()],
    resolve: {
      alias: [
        {
          find: /^@douyinfe\/semi-ui\/dist\/css\/semi\.min\.css$/,
          replacement: path.join(semiUiPkgDir, 'dist/css/semi.min.css'),
        },
      ],
    },
    define: {
      'process.env.NODE_ENV': JSON.stringify(mode === 'prod' ? 'production' : 'development'),
    },
    server: {
      port: 5173,
      strictPort: true,
      allowedHosts: ['.localhost'],
      proxy: {
        '/api': {
          target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: false,
        },
      },
    },
    build: {
      sourcemap: false,
      chunkSizeWarningLimit: 4000,
    },
  }
})
