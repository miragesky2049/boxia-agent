"""知识库文档权限目录：document:read/create/update/delete，并回填内置角色。

Revision ID: 0048_document_permissions
Revises: 0047_tenant_settings
Create Date: 2026-10-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_document_permissions"
down_revision: str | None = "0047_tenant_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("document:read", "知识库文档查看", "tool", "read", 200, ""),
    ("document:create", "知识库文档创建", "tool", "create", 201, ""),
    ("document:update", "知识库文档更新", "tool", "update", 202, ""),
    ("document:delete", "知识库文档删除", "tool", "delete", 203, ""),
)

_READ_CODES = ("document:read",)
_FULL_CODES = ("document:read", "document:create", "document:update", "document:delete")


def _permission_values() -> str:
    return ",\n        ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _PERMISSIONS
    )


def _code_array(codes: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def upgrade() -> None:
    """写入权限目录，并把知识库权限授予内置 superadmin/admin/viewer 角色。"""
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            {_permission_values()}
        ON CONFLICT (code) DO NOTHING
        """
    )

    # viewer 只读；superadmin/admin 全部 4 个权限。
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON (
            (r.code = 'viewer' AND p.code = ANY({_code_array(_READ_CODES)}))
            OR (r.code IN ('superadmin', 'admin') AND p.code = ANY({_code_array(_FULL_CODES)}))
        )
        WHERE r.is_system = TRUE
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    """回收知识库权限授权并从目录删除。"""
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(_FULL_CODES)})
        )
        """
    )
    op.execute(f"DELETE FROM permission_resources WHERE code = ANY({_code_array(_FULL_CODES)})")
