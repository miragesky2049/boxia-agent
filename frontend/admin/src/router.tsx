import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import RequireAuth from './auth/RequireAuth'
import RequirePermission from './auth/RequirePermission'
import PageLoading from './components/PageLoading'
import AdminLayout from './layouts/AdminLayout'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const ChangePasswordPage = lazy(() => import('./pages/ChangePasswordPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))
const AgentListPage = lazy(() => import('./pages/agents/AgentListPage'))
const AgentEditPage = lazy(() => import('./pages/agents/AgentEditPage'))
const WorkflowListPage = lazy(() => import('./pages/workflows/WorkflowListPage'))
const WorkflowEditPage = lazy(() => import('./pages/workflows/WorkflowEditPage'))
const ToolListPage = lazy(() => import('./pages/tools/ToolListPage'))
const UsersPage = lazy(() => import('./pages/UsersPage'))
const DepartmentsPage = lazy(() => import('./pages/departments/DepartmentsPage'))
const EmploymentsPage = lazy(() => import('./pages/employments/EmploymentsPage'))
const AdminUsersPage = lazy(() => import('./pages/AdminUsersPage'))
const UserGrantsPage = lazy(() => import('./pages/grants/UserGrantsPage'))
const TenantsPage = lazy(() => import('./pages/TenantsPage'))
const TenantDetailPage = lazy(() => import('./pages/tenants/TenantDetailPage'))
const RolesPage = lazy(() => import('./pages/RolesPage'))
const RoleDetailPage = lazy(() => import('./pages/roles/RoleDetailPage'))
const MgmtUnitsPage = lazy(() => import('./pages/mgmtUnits/MgmtUnitsPage'))
const MgmtUnitDetailPage = lazy(() => import('./pages/mgmtUnits/MgmtUnitDetailPage'))
const AppListPage = lazy(() => import('./pages/apps/AppListPage'))
const AppEditPage = lazy(() => import('./pages/apps/AppEditPage'))
const MarketplacePage = lazy(() => import('./pages/apps/MarketplacePage'))
const RunPage = lazy(() => import('./pages/apps/RunPage'))
const RunsPage = lazy(() => import('./pages/apps/RunsPage'))
const ResourcesPage = lazy(() => import('./pages/apps/ResourcesPage'))
const AuditLogsPage = lazy(() => import('./pages/AuditLogsPage'))

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
            <Route path="/" element={<Navigate to="/agents" replace />} />
            <Route path="/apps" element={<AppListPage />} />
            <Route path="/apps/:id/edit" element={<AppEditPage />} />
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
              path="/agents"
              element={
                <RequirePermission permission="page:agents">
                  <AgentListPage />
                </RequirePermission>
              }
            />
            <Route
              path="/agents/new"
              element={
                <RequirePermission permission="page:agents">
                  <AgentEditPage />
                </RequirePermission>
              }
            />
            <Route
              path="/agents/:id/edit"
              element={
                <RequirePermission permission="page:agents">
                  <AgentEditPage />
                </RequirePermission>
              }
            />
            <Route
              path="/workflows"
              element={
                <RequirePermission permission="page:workflows">
                  <WorkflowListPage />
                </RequirePermission>
              }
            />
            <Route
              path="/workflows/:id/edit"
              element={
                <RequirePermission permission="page:workflows">
                  <WorkflowEditPage />
                </RequirePermission>
              }
            />
            <Route
              path="/tools"
              element={
                <RequirePermission permission="page:tools">
                  <ToolListPage />
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
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
