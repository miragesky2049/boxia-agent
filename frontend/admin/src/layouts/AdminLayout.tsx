import {
  ApartmentOutlined,
  IdcardOutlined,
  KeyOutlined,
  LogoutOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SafetyOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Avatar, Dropdown, Layout, Menu, Tag } from 'antd'
import type { MenuProps } from 'antd'
import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useTenant } from '../tenant/TenantContext'
import './AdminLayout.css'

const { Header, Sider, Content } = Layout

const ROLE_LABELS = {
  superadmin: '超级管理员',
  admin: '管理员',
  viewer: '只读',
}

const MENU_META: Record<string, { icon: ReactNode; label: string }> = {
  agents: { icon: <RobotOutlined />, label: '智能体管理' },
  grants: { icon: <SafetyOutlined />, label: '授权管理' },
  roles: { icon: <SafetyCertificateOutlined />, label: '角色管理' },
  users: { icon: <IdcardOutlined />, label: '用户管理' },
  'admin-users': { icon: <TeamOutlined />, label: '管理员账号' },
  tenants: { icon: <ApartmentOutlined />, label: '租户管理' },
}

const ENV_LABELS = {
  local: '本地',
  dev: '开发',
  test: '测试',
  prod: '线上',
} as const

export default function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, signOut, systemRole, menus, mustChangePassword } = useAuth()
  const { platformName, scopeLabel, isPlatform, context } = useTenant()

  useEffect(() => {
    if (mustChangePassword) {
      navigate('/change-password', { replace: true })
    }
  }, [mustChangePassword, navigate])

  // 菜单以后端返回为准，前端只负责图标与文案映射
  const menuItems: MenuProps['items'] = menus.flatMap((key) => {
    const meta = MENU_META[key]
    return meta ? [{ key: `/${key}`, icon: meta.icon, label: meta.label }] : []
  })

  const selectedKey =
    menuItems.map((item) => String(item?.key)).find((key) => location.pathname.startsWith(key)) ??
    '/agents'

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
      <Sider width={224} theme="light" className="admin-sider">
        <div className="admin-sider__brand" onClick={() => navigate('/agents')}>
          <span className="admin-sider__logo">B</span>
          <span className="admin-sider__title">
            {platformName}
            <small>
              {scopeLabel}
              {context && context.app_env !== 'prod' ? ` · ${ENV_LABELS[context.app_env]}环境` : ''}
            </small>
          </span>
        </div>
        <Menu
          mode="inline"
          items={menuItems}
          selectedKeys={[selectedKey]}
          onClick={({ key }) => navigate(key)}
          className="admin-sider__menu"
        />
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
              {user && <Tag bordered={false}>{ROLE_LABELS[systemRole]}</Tag>}
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
