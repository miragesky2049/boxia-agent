"""权限码种子：button:tenant:delete（租户删除，仅平台 superadmin）。

Revision ID: 0063_tenant_delete_permission
Revises: 0062_entitlement_request_log
Create Date: 2026-11-04

设计要点：
- 租户物理删除为高危不可逆操作，仅授产品级平台租户（全零 UUID）下的 superadmin；
  admin/viewer 均不授予（区别于 0058 的 superadmin+admin）。
- 写法沿用 0058：permission_resources ON CONFLICT DO NOTHING，role_permissions
  INSERT ... SELECT 按角色 code 匹配，不写死 UUID。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0063_tenant_delete_permission"
down_revision: str | None = "0062_entitlement_request_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户全零 UUID（迁移不得 import 业务代码，与 0057/0058 同源字面量）
_PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"
_PERMISSION_CODE = "button:tenant:delete"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            (gen_random_uuid(), '{_PERMISSION_CODE}', '租户-删除', 'button',
             'delete', '', 282, TRUE)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = '{_PERMISSION_CODE}'
        WHERE r.is_system = TRUE
          AND r.code = 'superadmin'
          AND r.tenant_id = '{_PLATFORM_TENANT_ID}'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = '{_PERMISSION_CODE}'
        )
        """
    )
    op.execute(f"DELETE FROM permission_resources WHERE code = '{_PERMISSION_CODE}'")
