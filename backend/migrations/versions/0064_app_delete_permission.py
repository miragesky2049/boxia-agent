"""权限收紧：button:app:delete（应用删除）回收为仅平台 superadmin。

Revision ID: 0064_app_delete_permission
Revises: 0063_tenant_delete_permission
Create Date: 2026-11-04

背景：
- 0038 将 button:app:delete 授给了全部系统角色中的 superadmin/admin（未按租户过滤），
  应用物理删除为高危不可逆操作，该授权范围过宽。
- 本迁移回收平台 admin 及所有租户角色的授权，仅保留平台租户（全零 UUID）superadmin；
  与 0063 租户删除的授权口径及 PLATFORM_ONLY_CODES 保持一致。
- permission_resources 已由 0038 入库，此处仅 ON CONFLICT 兜底，不新增资源。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0064_app_delete_permission"
down_revision: str | None = "0063_tenant_delete_permission"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 平台租户全零 UUID（迁移不得 import 业务代码，与 0057/0058/0063 同源字面量）
_PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"
_PERMISSION_CODE = "button:app:delete"


def upgrade() -> None:
    # 权限资源兜底（正常已由 0038 写入）
    op.execute(
        f"""
        INSERT INTO permission_resources
            (id, code, name, category, action, description, sort_order, is_active)
        VALUES
            (gen_random_uuid(), '{_PERMISSION_CODE}', '应用-删除', 'button',
             'delete', '', 402, TRUE)
        ON CONFLICT (code) DO NOTHING
        """
    )
    # 回收：删除该权限对"非平台租户 superadmin"角色的全部既有授权
    op.execute(
        f"""
        DELETE FROM role_permissions rp
        USING roles r, permission_resources p
        WHERE rp.role_id = r.id
          AND rp.permission_id = p.id
          AND p.code = '{_PERMISSION_CODE}'
          AND (r.tenant_id IS DISTINCT FROM '{_PLATFORM_TENANT_ID}'
               OR r.code IS DISTINCT FROM 'superadmin')
        """
    )
    # 补种：平台租户 superadmin
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
    # 回滚为 0038 的授权状态：全部系统角色的 superadmin/admin（不区分租户）
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permission_resources WHERE code = '{_PERMISSION_CODE}'
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO role_permissions (id, role_id, permission_id)
        SELECT gen_random_uuid(), r.id, p.id
        FROM roles r
        JOIN permission_resources p ON p.code = '{_PERMISSION_CODE}'
        WHERE r.is_system = TRUE
          AND r.code = ANY (ARRAY['superadmin', 'admin'])
        ON CONFLICT DO NOTHING
        """
    )
