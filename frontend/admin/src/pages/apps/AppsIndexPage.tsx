import { useTenant } from '../../tenant/TenantContext'
import AppListPage from './AppListPage'
import TenantAppsPage from './TenantAppsPage'

export default function AppsIndexPage() {
  const { isPlatform } = useTenant()
  return isPlatform ? <AppListPage /> : <TenantAppsPage />
}
