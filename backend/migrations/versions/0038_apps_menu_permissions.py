"""应用管理/市场/资源菜单与页面权限，审计清空按钮，应用操作按钮。

Revision ID: 0038_apps_menu_permissions
Revises: 0037_drop_legacy
Create Date: 2026-10-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038_apps_menu_permissions"
down_revision: str | None = "0037_drop_legacy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:apps", "应用管理", "menu", "view", 10, ""),
    ("menu:marketplace", "应用市场", "menu", "view", 12, ""),
    ("menu:resources", "资源管理", "menu", "view", 14, ""),
    ("page:apps", "应用管理页面", "page", "view", 110, ""),
    ("page:marketplace", "应用市场页面", "page", "view", 112, ""),
    ("page:resources", "资源管理页面", "page", "view", 114, ""),
    ("button:audit:clear", "审计日志-清空", "button", "delete", 390, ""),
    ("button:app:create", "应用-新建", "button", "create", 400, ""),
    ("button:app:update", "应用-编辑", "button", "update", 401, ""),
    ("button:app:delete", "应用-删除", "button", "delete", 402, ""),
)

# 菜单/页面：所有内置角色（superadmin/admin/viewer）
_READ_CODES = (
    "menu:apps",
    "page:apps",
    "menu:marketplace",
    "page:marketplace",
    "menu:resources",
    "page:resources",
)

# 应用操作按钮：superadmin + admin
_APP_BUTTON_CODES = (
    "button:app:create",
    "button:app:update",
    "button:app:delete",
)

# 审计清空：仅 superadmin
_AUDIT_CLEAR_CODES = ("button:audit:clear",)


def _permission_values() -> str:
    return ",\n        ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _PERMISSIONS
    )


def _code_array(codes: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            {_permission_values()}
        ON CONFLICT (code) DO NOTHING
        """
    )

    # 菜单/页面：所有内置角色
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

    # 应用操作按钮：superadmin + admin
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON (
            r.code = ANY(ARRAY['superadmin', 'admin'])
            AND p.code = ANY({_code_array(_APP_BUTTON_CODES)})
        )
        WHERE r.is_system = TRUE
        ON CONFLICT DO NOTHING
        """
    )

    # 审计清空：仅 superadmin
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON (
            r.code = 'superadmin'
            AND p.code = ANY({_code_array(_AUDIT_CLEAR_CODES)})
        )
        WHERE r.is_system = TRUE
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    all_codes = _READ_CODES + _APP_BUTTON_CODES + _AUDIT_CLEAR_CODES
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(all_codes)})
        )
        """
    )
    op.execute(
        f"DELETE FROM permission_resources WHERE code = ANY({_code_array(all_codes)})"
    )
