"""角色授权菜单下线：/role-access 并入角色详情「数据授权」页签，收回 role-access 三码。

背景：「角色授权」页与「角色管理」详情页调用同一组端点、写同一份表
（role_permissions + resource_grants），功能权限页签与详情页 100% 重叠，
资源矩阵仅多批量授权与全员可见两个视图。参照行业单入口模式
（角色详情统一承载功能权限 + 数据授权），详情页数据授权页签已升级为
四类资源批量授权矩阵（含全员可见，仅租户角色），本迁移下线旧入口权限码：
- role_permissions 收回 menu:role-access / page:role-access / button:role-access:manage
  的全部授权（含租户内置角色与自定义角色）；
- permission_resources 删除上述三码，目录不再下发。

说明：
- 0058 为已发布迁移不改写历史；downgrade 按 0058 口径重新种子并仅恢复
  租户作用域 superadmin/admin 系统角色的授权（沿用 0067 后平台租户双字面量），
  自定义角色的历史授权无法精确还原。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073_role_access_removal"
down_revision: str | None = "0072_app_grant_to_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户 UUID 双字面量：全零旧值（0067 前）+ 新配置默认值（0067 后）；迁移不得 import 业务代码
_PLATFORM_TENANT_IDS = (
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-0000-0000-000000100000",
)

# 下线的三码（与 0058 种子 (code, name, category, action, sort_order, description) 同源）
_ROLE_ACCESS_CODES = ("menu:role-access", "page:role-access", "button:role-access:manage")
_ROLE_ACCESS_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:role-access", "角色授权", "menu", "view", 21, ""),
    ("page:role-access", "角色授权页面", "page", "view", 121, ""),
    ("button:role-access:manage", "角色授权-维护", "button", "manage", 301, ""),
)


def _platform_tenant_array() -> str:
    return "ARRAY[" + ", ".join(f"'{item}'::uuid" for item in _PLATFORM_TENANT_IDS) + "]"


def _code_array(codes: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def _tenant_roles_sql() -> str:
    # 租户作用域角色：有 tenant_id 且不属于平台租户（平台内置角色的 tenant_id 即平台租户）
    return (
        f"SELECT r.id FROM roles r "
        f"WHERE r.tenant_id IS NOT NULL AND r.tenant_id <> ALL({_platform_tenant_array()})"
    )


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(_ROLE_ACCESS_CODES)})
        )
        """
    )
    op.execute(
        f"DELETE FROM permission_resources WHERE code = ANY({_code_array(_ROLE_ACCESS_CODES)})"
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            (gen_random_uuid(), 'menu:role-access', '角色授权', 'menu', 'view', '', 21, TRUE),
            (gen_random_uuid(), 'page:role-access', '角色授权页面', 'page', 'view', '', 121, TRUE),
            (gen_random_uuid(), 'button:role-access:manage', '角色授权-维护', 'button', 'manage', '', 301, TRUE)
        ON CONFLICT (code) DO NOTHING
        """
    )
    # 还原 0058 口径：租户作用域 superadmin/admin 系统角色重新持有三码；自定义角色不还原
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = ANY({_code_array(_ROLE_ACCESS_CODES)})
        WHERE r.is_system = TRUE
          AND r.code IN ('superadmin', 'admin')
          AND r.id IN ({_tenant_roles_sql()})
        ON CONFLICT DO NOTHING
        """
    )
