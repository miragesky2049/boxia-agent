import { ConfigProvider } from '@douyinfe/semi-ui'
import zhCN from '@douyinfe/semi-ui/lib/es/locale/source/zh_CN'
import '@douyinfe/semi-ui/dist/css/semi.min.css'
// 53c93d5 画布重写时误删 antd <App> 包裹：App.useApp() 在无 Provider 时返回空上下文，
// 各页面 message/modal 调用运行时崩溃，这里恢复包裹（Semi 仅画布内部使用，两者共存）。
import { App as AntdApp } from 'antd'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import 'reflect-metadata'
import { createRoot } from 'react-dom/client'
import { AuthProvider } from './auth/AuthContext'
import AppErrorBoundary from './components/AppErrorBoundary'
import AppRouter from './router'
import './index.css'
import { TenantGate, TenantProvider } from './tenant/TenantContext'

dayjs.locale('zh-cn')

createRoot(document.getElementById('root')!).render(
  // <StrictMode>
  <ConfigProvider locale={zhCN}>
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
  </ConfigProvider>,
  // </StrictMode>
)
