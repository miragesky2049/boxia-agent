import RequirePermission from '../../auth/RequirePermission'
import { useTenant } from '../../tenant/TenantContext'
import AppListPage from './AppListPage'
import TenantAppAdminListPage from './TenantAppAdminListPage'

export default function AppsIndexPage() {
  const { isPlatform } = useTenant()
  // 0070 菜单合并：租户侧「应用管理」= 已订阅的产品级应用 + 我管理的应用，应用运行归用户端
  if (!isPlatform) {
    return (
      <RequirePermission permission="page:tenant-apps" tenantOnly>
        <TenantAppAdminListPage />
      </RequirePermission>
    )
  }
  return <AppListPage />
}
