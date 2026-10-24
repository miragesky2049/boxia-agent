import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import RequireAuth from './auth/RequireAuth'
import RequireRole from './auth/RequireRole'
import PageLoading from './components/PageLoading'
import AdminLayout from './layouts/AdminLayout'

const LoginPage = lazy(() => import('./pages/LoginPage'))
const ChangePasswordPage = lazy(() => import('./pages/ChangePasswordPage'))
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'))
const AgentListPage = lazy(() => import('./pages/agents/AgentListPage'))
const AgentEditPage = lazy(() => import('./pages/agents/AgentEditPage'))
const UsersPage = lazy(() => import('./pages/UsersPage'))
const AdminUsersPage = lazy(() => import('./pages/AdminUsersPage'))
const GrantsPage = lazy(() => import('./pages/grants/GrantsPage'))
const TenantsPage = lazy(() => import('./pages/TenantsPage'))
const RolesPage = lazy(() => import('./pages/RolesPage'))

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
            <Route path="/agents" element={<AgentListPage />} />
            <Route path="/agents/new" element={<AgentEditPage />} />
            <Route path="/agents/:id/edit" element={<AgentEditPage />} />
            <Route
              path="/grants"
              element={
                <RequireRole role="superadmin">
                  <GrantsPage />
                </RequireRole>
              }
            />
            <Route
              path="/roles"
              element={
                <RequireRole role="superadmin">
                  <RolesPage />
                </RequireRole>
              }
            />
            <Route
              path="/users"
              element={
                <RequireRole role="superadmin">
                  <UsersPage />
                </RequireRole>
              }
            />
            <Route
              path="/admin-users"
              element={
                <RequireRole role="superadmin">
                  <AdminUsersPage />
                </RequireRole>
              }
            />
            <Route
              path="/tenants"
              element={
                <RequireRole role="superadmin" platformOnly>
                  <TenantsPage />
                </RequireRole>
              }
            />
          </Route>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
