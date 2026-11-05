import { useCallback, useEffect, useState } from 'react'
import { App } from 'antd'
import { rolesApi } from '../api/access'
import type { AdminUser, Role } from '../api/types'
import { adminUsersApi } from '../api/users'
import { useAuth } from '../auth/AuthContext'
import { AdminUsersBlock } from '../components/admin-users/AdminUsersBlock'
import { useTenant } from '../tenant/TenantContext'

export default function AdminUsersPage() {
  const { user: currentUser, hasPermission } = useAuth()
  const canCreate = hasPermission('button:admin-user:create')
  const canUpdate = hasPermission('button:admin-user:update')
  const canDelete = hasPermission('button:admin-user:delete')
  const canResetPassword = hasPermission('button:admin-user:reset-password')
  const { isPlatform, context } = useTenant()
  const { message } = App.useApp()
  const [roles, setRoles] = useState<Role[]>([])
  const [items, setItems] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    rolesApi
      .list()
      .then((items) => setRoles(items.filter((role) => role.is_active)))
      .catch(() => setRoles([]))
  }, [isPlatform])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await adminUsersApi.list({
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, message])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <h2 className="page-header__title">管理员账号</h2>
          <p className="page-header__desc">
            {isPlatform
              ? '产品级管理员仅能登录产品级平台，可绑定平台自有角色；角色决定其可访问的平台级资源。'
              : '展示本租户内拥有超级管理员或管理员角色的账号，可在此调整角色与启用状态。'}
          </p>
        </div>
      </div>

      <AdminUsersBlock
        roles={roles}
        passwordPolicy={context?.password_policy}
        currentUserId={currentUser?.id ?? null}
        canCreate={canCreate}
        canUpdate={canUpdate}
        canDelete={canDelete}
        canResetPassword={canResetPassword}
        dataSource={items}
        loading={loading}
        pagination={{
          page,
          pageSize,
          total,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
        onSearch={(value) => {
          setKeyword(value)
          setPage(1)
        }}
        onCreate={async (payload) => {
          await adminUsersApi.create(payload)
          await load()
        }}
        onUpdate={async (id, payload) => {
          await adminUsersApi.update(id, payload)
          await load()
        }}
        onRemove={async (id) => {
          await adminUsersApi.remove(id)
          await load()
        }}
        onResetPassword={async (id, password) => {
          await adminUsersApi.resetPassword(id, password)
        }}
        onToggleActive={async (id, enabled) => {
          await adminUsersApi.update(id, { is_active: enabled })
          await load()
        }}
        roleLabel={isPlatform ? '平台角色' : '租户角色'}
      />
    </div>
  )
}
