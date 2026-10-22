import '@ant-design/v5-patch-for-react-19'
import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import 'antd/dist/reset.css'
import './index.css'
import { AuthProvider } from './auth/AuthContext'
import AppErrorBoundary from './components/AppErrorBoundary'
import AppRouter from './router'
import { TenantGate, TenantProvider } from './tenant/TenantContext'

dayjs.locale('zh-cn')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#2f6bff',
          borderRadius: 8,
          colorText: '#1d2129',
        },
      }}
    >
      <AntdApp>
        <TenantProvider>
          <TenantGate>
            <AuthProvider>
              <AppErrorBoundary>
                <AppRouter />
              </AppErrorBoundary>
            </AuthProvider>
          </TenantGate>
        </TenantProvider>
      </AntdApp>
    </ConfigProvider>
  </StrictMode>,
)
