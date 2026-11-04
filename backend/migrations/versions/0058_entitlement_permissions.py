"""权限码种子：租户开通/角色授权/资源审核/资源新建 + 内置角色授权（可独立发布）。

Revision ID: 0058_entitlement_permissions
Revises: 0057_grant_subject_type
Create Date: 2026-11-03

设计要点（P1-4）：
- 平台侧 4 码（entitlements + resource:review）授平台租户（全零 UUID）下的 superadmin/admin；
  租户侧 4 码（role-access + resource:create）授真实租户下的 superadmin/admin；viewer 均不授予。
- 写法沿用 0038：_PERMISSIONS + ON CONFLICT DO NOTHING + INSERT ... SELECT 按角色 code 匹配，不写死 UUID。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0058_entitlement_permissions"
down_revision: str | None = "0057_grant_subject_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户全零 UUID（迁移不得 import 业务代码，与 0057 同源字面量）
_PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# (code, name, category, action, sort_order, description)
_PERMISSIONS: tuple[tuple[str, str, str, str, int, str], ...] = (
    ("menu:entitlements", "租户开通", "menu", "view", 15, ""),
    ("page:entitlements", "租户开通页面", "page", "view", 115, ""),
    ("button:entitlement:manage", "租户开通-维护", "button", "manage", 405, ""),
    ("button:resource:review", "资源-审核", "button", "manage", 406, ""),
    ("menu:role-access", "角色授权", "menu", "view", 21, ""),
    ("page:role-access", "角色授权页面", "page", "view", 121, ""),
    ("button:role-access:manage", "角色授权-维护", "button", "manage", 301, ""),
    ("button:resource:create", "资源-新建", "button", "create", 302, ""),
)

# 平台侧：superadmin/admin 获得租户开通与资源审核
_PLATFORM_CODES = (
    "menu:entitlements",
    "page:entitlements",
    "button:entitlement:manage",
    "button:resource:review",
)
# 租户侧：superadmin/admin 获得角色授权与资源新建
_TENANT_CODES = (
    "menu:role-access",
    "page:role-access",
    "button:role-access:manage",
    "button:resource:create",
)


def _permission_values() -> str:
    return ",\n            ".join(
        f"(gen_random_uuid(), '{code}', '{name}', '{category}', "
        f"'{action}', '{description}', {sort_order}, TRUE)"
        for code, name, category, action, sort_order, description in _PERMISSIONS
    )


def _code_array(codes: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{code}'" for code in codes) + "]"


def _grant_sql(codes: Sequence[str], tenant_predicate: str) -> str:
    return f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = ANY({_code_array(codes)})
        WHERE r.is_system = TRUE
          AND r.code IN ('superadmin', 'admin')
          AND {tenant_predicate}
        ON CONFLICT DO NOTHING
    """


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
    op.execute(_grant_sql(_PLATFORM_CODES, f"r.tenant_id = '{_PLATFORM_TENANT_ID}'"))
    op.execute(_grant_sql(_TENANT_CODES, f"r.tenant_id != '{_PLATFORM_TENANT_ID}'"))


def downgrade() -> None:
    all_codes = _PLATFORM_CODES + _TENANT_CODES
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = ANY({_code_array(all_codes)})
        )
        """
    )
    op.execute(f"DELETE FROM permission_resources WHERE code = ANY({_code_array(all_codes)})")
