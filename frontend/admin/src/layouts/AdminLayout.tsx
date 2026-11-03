import {
  ApartmentOutlined,
  AppstoreOutlined,
  BankOutlined,
  ClusterOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  GiftOutlined,
  IdcardOutlined,
  KeyOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SafetyCertificateOutlined,
  SafetyOutlined,
  ShopOutlined,
  TeamOutlined,
  UserOutlined,
  UserSwitchOutlined,
} from '@ant-design/icons'
import { Avatar, Dropdown, Layout, Menu, Tag, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import './AdminLayout.css'

const { Header, Sider, Content } = Layout

const MENU_META: Record<string, { icon: ReactNode; label: string }> = {
  apps: { icon: <AppstoreOutlined />, label: '应用管理' },
  marketplace: { icon: <ShopOutlined />, label: '应用市场' },
  resources: { icon: <DatabaseOutlined />, label: '资源管理' },
  grants: { icon: <SafetyOutlined />, label: '用户授权' },
  users: { icon: <TeamOutlined />, label: '用户管理' },
  roles: { icon: <SafetyCertificateOutlined />, label: '角色管理' },
  departments: { icon: <ClusterOutlined />, label: '部门管理' },
  employments: { icon: <IdcardOutlined />, label: '任职管理' },
  'mgmt-units': { icon: <BankOutlined />, label: '管理单元' },
  'admin-users': { icon: <UserSwitchOutlined />, label: '管理员账号' },
  tenants: { icon: <ApartmentOutlined />, label: '租户管理' },
  audit: { icon: <FileSearchOutlined />, label: '审计日志' },
  entitlements: { icon: <GiftOutlined />, label: '租户开通' },
  'role-access': { icon: <KeyOutlined />, label: '角色授权' },
}

interface MenuGroup {
  icon: ReactNode
  label: string
  children: string[]
}

const MENU_GROUPS: Record<string, MenuGroup> = {
  organization: {
    icon: <ClusterOutlined />,
    label: '组织架构',
    children: ['departments', 'employments', 'mgmt-units'],
  },
}

const ENV_LABELS = {
  local: '本地',
  dev: '开发',
  test: '测试',
  prod: '线上',
} as const

const SIDER_WIDTH = 224
const SIDER_COLLAPSED_WIDTH = 64
const SIDER_COLLAPSE_KEY = 'admin:sider:collapsed'

export default function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, signOut, roleName, menus, mustChangePassword } = useAuth()
  const { platformName, scopeLabel, isPlatform, context } = useTenant()

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false
    return window.localStorage.getItem(SIDER_COLLAPSE_KEY) === '1'
  })

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      window.localStorage.setItem(SIDER_COLLAPSE_KEY, next ? '1' : '0')
      return next
    })
  }

  useEffect(() => {
    if (mustChangePassword) {
      navigate('/change-password', { replace: true })
    }
  }, [mustChangePassword, navigate])

  // 菜单以后端返回为准，前端只负责图标、文案与分组映射
  const groupedKeys = new Set(Object.values(MENU_GROUPS).flatMap((group) => group.children))
  const menuItems: MenuProps['items'] = []
  menus.forEach((key) => {
    if (!groupedKeys.has(key)) {
      const meta = MENU_META[key]
      if (meta) {
        menuItems.push({ key: `/${key}`, icon: meta.icon, label: meta.label })
      }
      return
    }
    const groupEntry = Object.entries(MENU_GROUPS).find(([, group]) => group.children.includes(key))
    if (!groupEntry) return
    const [groupKey, group] = groupEntry
    const groupMenuKey = `group:${groupKey}`
    if (menuItems.some((item) => item && 'key' in item && item.key === groupMenuKey)) return
    const children: NonNullable<MenuProps['items']> = group.children
      .filter((child) => menus.includes(child))
      .flatMap((child) => {
        const meta = MENU_META[child]
        return meta ? [{ key: `/${child}`, icon: meta.icon, label: meta.label }] : []
      })
    if (children.length > 0) {
      menuItems.push({
        key: groupMenuKey,
        icon: group.icon,
        label: group.label,
        children,
      })
    }
  })

  const selectedKey =
    menus
      .map((key) => `/${key}`)
      .sort((left, right) => right.length - left.length)
      .find((candidate) => location.pathname.startsWith(candidate)) ?? '/apps'

  const userMenu: MenuProps['items'] = [
    {
      key: 'change-password',
      icon: <KeyOutlined />,
      label: '修改密码',
      onClick: () => navigate('/change-password'),
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      onClick: () => {
        void signOut().finally(() => navigate('/login', { replace: true }))
      },
    },
  ]

  return (
    <Layout className="admin-layout">
      <Sider
        width={SIDER_WIDTH}
        collapsedWidth={SIDER_COLLAPSED_WIDTH}
        collapsed={collapsed}
        theme="light"
        className="admin-sider"
        trigger={null}
      >
        <div
          className="admin-sider__brand"
          onClick={() => navigate('/apps')}
          title={collapsed ? platformName : undefined}
        >
          <span className="admin-sider__logo">B</span>
          {!collapsed && (
            <span className="admin-sider__title">
              {platformName}
              <small>
                {scopeLabel}
                {context && context.app_env !== 'prod'
                  ? ` · ${ENV_LABELS[context.app_env]}环境`
                  : ''}
              </small>
            </span>
          )}
        </div>
        <Menu
          mode="inline"
          items={menuItems}
          selectedKeys={[selectedKey]}
          onClick={({ key }) => navigate(key)}
          className="admin-sider__menu"
          inlineCollapsed={collapsed}
        />
        <Tooltip title={collapsed ? '展开导航' : '收起导航'} placement="right">
          <button
            type="button"
            className="admin-sider__trigger"
            onClick={toggleCollapsed}
            aria-label={collapsed ? '展开导航' : '收起导航'}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
        </Tooltip>
      </Sider>

      <Layout>
        <Header className="admin-header">
          <div className="admin-header__crumb">
            <Tag color={isPlatform ? 'geekblue' : 'green'} bordered={false}>
              {isPlatform ? '产品级' : '租户级'}
            </Tag>
            {scopeLabel}
          </div>
          <Dropdown menu={{ items: userMenu }} placement="bottomRight" trigger={['click']}>
            <button type="button" className="admin-header__user">
              <Avatar size={30} icon={<UserOutlined />} />
              <span>{user?.display_name || user?.username}</span>
              {user && roleName && <Tag bordered={false}>{roleName}</Tag>}
            </button>
          </Dropdown>
        </Header>

        <Content className="admin-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
