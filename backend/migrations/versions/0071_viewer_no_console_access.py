"""出厂设置调整：只读成员（viewer）不再预置「管理端访问」system:console:access。

- 平台域（0010 播种的 viewer）与租户域（各租户 viewer）一并收回；
  viewer 账号登录管理端将被拒绝（403 账号未获得管理端访问权限），
  其被授权的业务对象改由用户端查看。
- 仅收回 is_system=TRUE 且 code='viewer' 的内置角色；
  自定义角色的管理端访问不受影响。
- 域模型同步：internal/domain/entity/permission.py 的
  PLATFORM_VIEWER_CODES 已剔除 CONSOLE_ACCESS（TENANT_VIEWER_CODES 经交集推导生效）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0071_viewer_no_console_access"
down_revision: str | None = "0070_app_menu_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSOLE_CODE = "system:console:access"


def _viewer_roles_sql() -> str:
    return "SELECT r.id FROM roles r WHERE r.is_system = TRUE AND r.code = 'viewer'"


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = '{_CONSOLE_CODE}'
        )
        AND role_id IN ({_viewer_roles_sql()})
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = '{_CONSOLE_CODE}'
        WHERE r.id IN ({_viewer_roles_sql()})
        ON CONFLICT DO NOTHING
        """
    )
