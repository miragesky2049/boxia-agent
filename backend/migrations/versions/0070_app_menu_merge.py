"""租户侧应用菜单合并：应用管理统一为 menu:tenant-apps，收回租户域的 menu:apps/page:apps。

背景：租户 console 曾同时存在「应用管理」(menu:apps，点开即运行卡片) 与「应用配置」
(menu:tenant-apps，可见/管理范围) 两个入口，职责易混淆。合并后：
- 租户侧「应用管理」菜单 = /apps 租户分支（已订阅的产品级应用 + 我管理的应用），
  入口权限由 menu:tenant-apps / page:tenant-apps 承载；
- 面向普通用户的应用运行移到用户端，租户 console 不再下发 menu:apps/page:apps；
- menu:apps/page:apps 保留在平台域（平台 console 的应用管理列表不受影响）。

说明：
- 收回范围 = 租户作用域的全部角色（含自定义角色），自定义角色上的历史授权无法在
  downgrade 精确还原；但收回后这两个码在域模型中已是平台专属，还原本身即过时语义。
- 存量授权清理条件与 0068 授予口径互补：仅收回 tenant_id 非平台租户的角色。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0070_app_menu_merge"
down_revision: str | None = "0069_app_admin_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户 UUID 双字面量：全零旧值（0067 前）+ 新配置默认值（0067 后）；迁移不得 import 业务代码
_PLATFORM_TENANT_IDS = (
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-0000-0000-000000100000",
)

_APP_MENU_CODES = ("menu:apps", "page:apps")


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
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(_APP_MENU_CODES)})
        )
        AND role_id IN ({_tenant_roles_sql()})
        """
    )
    # 更名与域模型目录（permission.py）保持一致：租户侧「应用管理」由 menu:tenant-apps 承载
    op.execute(
        "UPDATE permission_resources SET name = '应用管理', "
        "description = '租户侧应用管理入口（已订阅应用与可见/管理范围配置）' "
        "WHERE code = 'menu:tenant-apps'"
    )
    op.execute(
        "UPDATE permission_resources SET name = '应用管理页面', "
        "description = '租户应用管理页面（已订阅应用与我管理的应用）' "
        "WHERE code = 'page:tenant-apps'"
    )


def downgrade() -> None:
    # 还原为 0038/0068 之前的口径：租户内置系统角色重新持有应用菜单/页面码；
    # 自定义角色的历史授权不还原（收回后该码已属平台域，语义过时）
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = ANY({_code_array(_APP_MENU_CODES)})
        WHERE r.is_system = TRUE
          AND r.code IN ('superadmin', 'admin', 'viewer')
          AND r.id IN ({_tenant_roles_sql()})
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "UPDATE permission_resources SET name = '应用配置', "
        "description = '租户侧产品级应用管理入口' WHERE code = 'menu:tenant-apps'"
    )
    op.execute(
        "UPDATE permission_resources SET name = '应用配置页面', "
        "description = '租户应用可见范围配置页面' WHERE code = 'page:tenant-apps'"
    )
