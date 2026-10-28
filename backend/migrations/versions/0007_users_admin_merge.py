"""users multi-role & admin merge：end_user 改名 user，租户管理员并入用户表

Revision ID: 0007_users_admin_merge
Revises: 0006_roles_and_resource_access
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_users_admin_merge"
down_revision: str | None = "0006_roles_and_resource_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = [
    # end_user → user：表、约束、索引、触发器统一更名
    "ALTER TABLE end_users RENAME TO users",
    "ALTER TABLE users RENAME CONSTRAINT ux_end_users_tenant_username "
    "TO ux_users_tenant_username",
    "ALTER TABLE users RENAME CONSTRAINT fk_end_users_role_tenant TO fk_users_role_tenant",
    "ALTER INDEX ix_end_users_tenant_role RENAME TO ix_users_tenant_role",
    "ALTER TRIGGER trg_end_users_updated_at ON users RENAME TO trg_users_updated_at",
    "ALTER TABLE end_user_refresh_tokens RENAME TO user_refresh_tokens",
    "ALTER INDEX ix_end_user_refresh_tokens_user_id RENAME TO ix_user_refresh_tokens_user_id",
    "ALTER INDEX ix_end_user_refresh_tokens_family_id "
    "RENAME TO ix_user_refresh_tokens_family_id",
    "ALTER INDEX ix_end_user_refresh_tokens_expires_at "
    "RENAME TO ix_user_refresh_tokens_expires_at",
    "ALTER TABLE user_refresh_tokens RENAME CONSTRAINT "
    "end_user_refresh_tokens_user_id_fkey TO fk_user_refresh_tokens_user",
    # 用户多角色：users.role_id 保留为主角色，关联表维护完整角色集合
    """
    CREATE TABLE user_roles (
        id          BIGSERIAL   PRIMARY KEY,
        user_id     BIGINT      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role_id     BIGINT      NOT NULL,
        tenant_id   BIGINT      NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ux_user_roles_user_role UNIQUE (user_id, role_id),
        CONSTRAINT fk_user_roles_role_tenant
            FOREIGN KEY (role_id, tenant_id)
            REFERENCES roles(id, tenant_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_user_roles_role ON user_roles (tenant_id, role_id)",
    # 存量租户管理员迁入 users；用户名冲突时保留现有用户
    """
    INSERT INTO users (tenant_id, username, password_hash, display_name,
                       is_active, role_id, token_version, failed_login_count,
                       locked_until, last_login_at)
    SELECT au.tenant_id, au.username, au.password_hash, au.display_name,
           au.is_active, au.role_id, au.token_version, au.failed_login_count,
           au.locked_until, au.last_login_at
      FROM admin_users au
     WHERE au.tenant_id IS NOT NULL
       AND au.role_id IS NOT NULL
    ON CONFLICT (tenant_id, username) DO NOTHING
    """,
    # 迁移后的用户补齐角色关联；同名的已有用户也补上管理员角色
    """
    INSERT INTO user_roles (user_id, role_id, tenant_id)
    SELECT u.id, u.role_id, u.tenant_id
      FROM users u
    ON CONFLICT (user_id, role_id) DO NOTHING
    """,
    """
    INSERT INTO user_roles (user_id, role_id, tenant_id)
    SELECT u.id, au.role_id, au.tenant_id
      FROM admin_users au
      JOIN users u
        ON u.tenant_id = au.tenant_id
       AND u.username = au.username
     WHERE au.tenant_id IS NOT NULL
       AND au.role_id IS NOT NULL
    ON CONFLICT (user_id, role_id) DO NOTHING
    """,
    # 租户管理员不再单独存 admin_users，只保留产品级平台账号
    "DELETE FROM admin_users WHERE tenant_id IS NOT NULL",
    """
    ALTER TABLE admin_users
        ADD CONSTRAINT ck_admin_users_platform_only CHECK (tenant_id IS NULL)
    """,
]

_DOWNGRADE = [
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS ck_admin_users_platform_only",
    "DROP INDEX IF EXISTS ix_user_roles_role",
    "DROP TABLE IF EXISTS user_roles",
    "ALTER TABLE user_refresh_tokens RENAME CONSTRAINT fk_user_refresh_tokens_user TO "
    "end_user_refresh_tokens_user_id_fkey",
    "ALTER INDEX ix_user_refresh_tokens_expires_at "
    "RENAME TO ix_end_user_refresh_tokens_expires_at",
    "ALTER INDEX ix_user_refresh_tokens_family_id "
    "RENAME TO ix_end_user_refresh_tokens_family_id",
    "ALTER INDEX ix_user_refresh_tokens_user_id RENAME TO ix_end_user_refresh_tokens_user_id",
    "ALTER TABLE user_refresh_tokens RENAME TO end_user_refresh_tokens",
    "ALTER TRIGGER trg_users_updated_at ON users RENAME TO trg_end_users_updated_at",
    "ALTER INDEX ix_users_tenant_role RENAME TO ix_end_users_tenant_role",
    "ALTER TABLE users RENAME CONSTRAINT fk_users_role_tenant TO fk_end_users_role_tenant",
    "ALTER TABLE users RENAME CONSTRAINT ux_users_tenant_username TO ux_end_users_tenant_username",
    "ALTER TABLE users RENAME TO end_users",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
