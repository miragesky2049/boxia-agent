import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import RequirePermission from './auth/RequirePermission'
import PageLoading from './components/PageLoading'
import AdminLayout from './layouts/AdminLayout'
import { useTenant } from './tenant/TenantContext'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const ChangePasswordPage = lazy(() => import('./pages/ChangePasswordPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))
const UsersPage = lazy(() => import('./pages/UsersPage'))
const DepartmentsPage = lazy(() => import('./pages/departments/DepartmentsPage'))
const EmploymentsPage = lazy(() => import('./pages/employments/EmploymentsPage'))
const AdminUsersPage = lazy(() => import('./pages/AdminUsersPage'))
const UserGrantsPage = lazy(() => import('./pages/grants/UserGrantsPage'))
const TenantsPage = lazy(() => import('./pages/TenantsPage'))
const TenantDetailPage = lazy(() => import('./pages/tenants/TenantDetailPage'))
const TenantSettingsPage = lazy(() => import('./pages/tenants/TenantSettingsPage'))
const RolesPage = lazy(() => import('./pages/RolesPage'))
const RoleDetailPage = lazy(() => import('./pages/roles/RoleDetailPage'))
const MgmtUnitsPage = lazy(() => import('./pages/mgmtUnits/MgmtUnitsPage'))
const MgmtUnitDetailPage = lazy(() => import('./pages/mgmtUnits/MgmtUnitDetailPage'))
const AppsIndexPage = lazy(() => import('./pages/apps/AppsIndexPage'))
const AppEditPage = lazy(() => import('./pages/apps/AppEditPage'))
const AgentConfigPage = lazy(() => import('./pages/apps/AgentConfigPage'))
const TenantAppDetailPage = lazy(() => import('./pages/apps/TenantAppDetailPage'))
const EvalWorkspacePage = lazy(() => import('./pages/apps/EvalWorkspacePage'))
const MarketplacePage = lazy(() => import('./pages/apps/MarketplacePage'))
const RunPage = lazy(() => import('./pages/apps/RunPage'))
const RunsPage = lazy(() => import('./pages/apps/RunsPage'))
const ResourcesPage = lazy(() => import('./pages/apps/ResourcesPage'))
const AuditLogsPage = lazy(() => import('./pages/AuditLogsPage'))
const TenantEntitlementsPage = lazy(() => import('./pages/entitlements/TenantEntitlementsPage'))
const ApplyWorkbench = lazy(() => import('./pages/entitlements/ApplyWorkbench'))

export default function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/change-password"
            element={
              <RequireAuth>
                <ChangePasswordPage />
              </RequireAuth>
            }
          />
          <Route
            element={
              <RequireAuth>
                <AdminLayout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<LandingRedirect />} />
            <Route path="/apps" element={<AppsIndexPage />} />
            <Route path="/apps/:id/edit" element={<AppEditPage />} />
            {/* 0074：智能体应用的编辑入口是配置表单页，画布仍可从页内“打开画布”进入 */}
            <Route path="/apps/:id/agent" element={<AgentConfigPage />} />
            <Route path="/apps/:appId/eval" element={<EvalWorkspacePage />} />
            <Route path="/tenant-apps" element={<Navigate to="/apps" replace />} />
            <Route
              path="/tenant-apps/:appId"
              element={
                <RequirePermission permission="page:tenant-apps" tenantOnly>
                  <TenantAppDetailPage />
                </RequirePermission>
              }
            />
            <Route path="/marketplace" element={<MarketplacePage />} />
            <Route path="/marketplace/apps/:appId/run" element={<RunPage />} />
            <Route path="/marketplace/apps/:appId/runs" element={<RunsPage />} />
            <Route path="/resources" element={<ResourcesPage />} />
            <Route
              path="/audit"
              element={
                <RequirePermission permission="page:audit">
                  <AuditLogsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/grants"
              element={
                <RequirePermission permission="page:grants" tenantOnly>
                  <UserGrantsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/roles"
              element={
                <RequirePermission permission="page:roles">
                  <RolesPage />
                </RequirePermission>
              }
            />
            <Route
              path="/roles/:id"
              element={
                <RequirePermission permission="page:roles">
                  <RoleDetailPage />
                </RequirePermission>
              }
            />
            <Route
              path="/users"
              element={
                <RequirePermission permission="page:users">
                  <UsersPage />
                </RequirePermission>
              }
            />
            <Route
              path="/departments"
              element={
                <RequirePermission permission="page:departments" tenantOnly>
                  <DepartmentsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/employments"
              element={
                <RequirePermission permission="page:employments" tenantOnly>
                  <EmploymentsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/mgmt-units"
              element={
                <RequirePermission permission="page:mgmt-units" tenantOnly>
                  <MgmtUnitsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/mgmt-units/:id"
              element={
                <RequirePermission permission="page:mgmt-units" tenantOnly>
                  <MgmtUnitDetailPage />
                </RequirePermission>
              }
            />
            <Route
              path="/admin-users"
              element={
                <RequirePermission permission="page:admin-users">
                  <AdminUsersPage />
                </RequirePermission>
              }
            />
            <Route
              path="/tenants"
              element={
                <RequirePermission permission="page:tenants" platformOnly>
                  <TenantsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/tenants/:id"
              element={
                <RequirePermission permission="page:tenants" platformOnly>
                  <TenantDetailPage />
                </RequirePermission>
              }
            />
            <Route
              path="/tenants/:id/settings"
              element={
                <RequirePermission permission="page:tenants" platformOnly>
                  <TenantSettingsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/entitlements"
              element={
                <RequirePermission permission="page:entitlements" platformOnly>
                  <TenantEntitlementsPage />
                </RequirePermission>
              }
            />
            <Route
              path="/apply-workbench"
              element={
                <RequirePermission permission="page:entitlements" platformOnly>
                  <ApplyWorkbench />
                </RequirePermission>
              }
            />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

function LandingRedirect() {
  const { loading, user, hasPermission } = useAuth()
  const { isPlatform } = useTenant()
  if (loading || !user) return <PageLoading />
  // 租户 viewer 无应用管理入口权限（0070 收回 menu:apps），落地到应用市场
  if (isPlatform || hasPermission('page:tenant-apps')) return <Navigate to="/apps" replace />
  return <Navigate to="/marketplace" replace />
}
