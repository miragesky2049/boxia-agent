"""admin_users 仅保留产品级账号：移除租户归属与租户角色字段

Revision ID: 0008_admin_users_platform_only
Revises: 0007_users_admin_merge
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_admin_users_platform_only"
down_revision: str | None = "0007_users_admin_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    # 租户账号已并入 users，admin_users 不再需要租户维度
    "DROP INDEX IF EXISTS ux_admin_users_tenant_username",
    "DROP INDEX IF EXISTS ix_admin_users_tenant",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS ck_admin_users_platform_only",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS fk_admin_users_role_tenant",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS ck_admin_users_role_binding",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS role_id",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS tenant_id",
    # 平台用户名全局唯一
    "CREATE UNIQUE INDEX ux_admin_users_username ON admin_users (username)",
]

_DOWNGRADE = [
    "DROP INDEX IF EXISTS ux_admin_users_username",
    "ALTER TABLE admin_users ADD COLUMN tenant_id BIGINT "
    "REFERENCES tenants(id) ON DELETE RESTRICT",
    "ALTER TABLE admin_users ADD COLUMN role_id BIGINT",
    "CREATE INDEX ix_admin_users_tenant ON admin_users (tenant_id)",
    """
    CREATE UNIQUE INDEX ux_admin_users_tenant_username
        ON admin_users (COALESCE(tenant_id, 0), username)
    """,
    """
    ALTER TABLE admin_users ADD CONSTRAINT ck_admin_users_role_binding
        CHECK (tenant_id IS NULL OR role_id IS NOT NULL)
    """,
    """
    ALTER TABLE admin_users ADD CONSTRAINT fk_admin_users_role_tenant
        FOREIGN KEY (role_id, tenant_id)
        REFERENCES roles(id, tenant_id) ON DELETE RESTRICT
    """,
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
