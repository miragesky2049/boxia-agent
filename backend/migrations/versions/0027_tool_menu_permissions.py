"""工具管理菜单/页面权限：menu:tools / page:tools，并回填内置角色。

Revision ID: 0027_tool_menu_permissions
Revises: 0026_workflow_permissions
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_tool_menu_permissions"
down_revision: str | None = "0026_workflow_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:tools", "工具管理", "menu", "view", 16, ""),
    ("page:tools", "工具管理页面", "page", "view", 116, ""),
)

_READ_CODES = ("menu:tools", "page:tools")


def _permission_values() -> str:
    return ",\n        ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _PERMISSIONS
    )


def _code_array(codes: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def upgrade() -> None:
    """写入权限目录，并把工具菜单/页面授予内置 superadmin/admin/viewer 角色。"""
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            {_permission_values()}
        ON CONFLICT (code) DO NOTHING
        """
    )

    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON (
            r.code = ANY(ARRAY['superadmin', 'admin', 'viewer'])
            AND p.code = ANY({_code_array(_READ_CODES)})
        )
        WHERE r.is_system = TRUE
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """回收工具权限授权并从目录删除。"""
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(_READ_CODES)})
        )
        """
    )
    op.execute(f"DELETE FROM permission_resources WHERE code = ANY({_code_array(_READ_CODES)})")
