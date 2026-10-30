import { ConfigProvider } from '@douyinfe/semi-ui';
import zhCN from '@douyinfe/semi-ui/lib/es/locale/source/zh_CN';
import '@douyinfe/semi-ui/dist/css/semi.min.css';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import 'reflect-metadata';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AuthProvider } from './auth/AuthContext';
import AppErrorBoundary from './components/AppErrorBoundary';
import AppRouter from './router';
import './index.css';
import { TenantGate, TenantProvider } from './tenant/TenantContext';

dayjs.locale('zh-cn');

createRoot(document.getElementById('root')!).render(
  // <StrictMode>
  <ConfigProvider locale={zhCN}>
    <TenantProvider>
      <TenantGate>
        <AuthProvider>
          <AppErrorBoundary>
            <AppRouter />
          </AppErrorBoundary>
        </AuthProvider>
      </TenantGate>
    </TenantProvider>
  </ConfigProvider>
  // </StrictMode>
);
