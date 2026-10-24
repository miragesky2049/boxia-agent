"""平台自有角色体系与平台资源授权

Revision ID: 0010_platform_roles
Revises: 0009_strict_rbac_grants
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_platform_roles"
down_revision: str | None = "0009_strict_rbac_grants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE_TABLES = (
    ("agent", "agents"),
    ("skill", "skills"),
    ("tool", "tools"),
    ("component", "components"),
    ("prompt", "prompts"),
)

_UPGRADE = [
    # 角色归属为空表示平台自有角色，与租户角色数据隔离
    "ALTER TABLE roles ALTER COLUMN tenant_id DROP NOT NULL",
    """
    CREATE UNIQUE INDEX ux_roles_platform_code
        ON roles (lower(code)) WHERE tenant_id IS NULL
    """,
    """
    CREATE UNIQUE INDEX ux_roles_platform_name
        ON roles (lower(name)) WHERE tenant_id IS NULL
    """,
    # 平台系统角色种子；租户角色由租户创建时生成
    """
    INSERT INTO roles (tenant_id, code, name, description, system_role, is_system, is_active)
    SELECT NULL, v.code, v.name, v.description, v.code, TRUE, TRUE
      FROM (VALUES
            ('superadmin', '超级管理员', '平台最高权限，默认可访问全部平台级资源'),
            ('admin',      '管理员',     '可读写被授权的平台级资源'),
            ('viewer',     '只读成员',   '只读访问被授权的平台级资源')
      ) AS v(code, name, description)
     WHERE NOT EXISTS (
            SELECT 1 FROM roles r
             WHERE r.tenant_id IS NULL AND lower(r.code) = v.code
      )
    """,
    # 平台管理员账号绑定平台角色
    """
    ALTER TABLE admin_users
        ADD COLUMN role_id BIGINT REFERENCES roles(id) ON DELETE RESTRICT
    """,
    "CREATE INDEX ix_admin_users_role ON admin_users (role_id)",
    """
    UPDATE admin_users au
       SET role_id = r.id
      FROM roles r
     WHERE au.role_id IS NULL
       AND r.tenant_id IS NULL
       AND r.code = au.role
    """,
    # 平台级资源授权：tenant_id 为空时 role_id 必须指定角色
    "ALTER TABLE resource_grants ALTER COLUMN tenant_id DROP NOT NULL",
    """
    ALTER TABLE resource_grants
        ADD CONSTRAINT ck_resource_grants_scope
        CHECK (tenant_id IS NOT NULL OR role_id IS NOT NULL)
    """,
    """
    ALTER TABLE resource_grants
        ADD CONSTRAINT fk_resource_grants_role
        FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
    """,
    """
    CREATE UNIQUE INDEX ux_resource_grants_platform_role
        ON resource_grants (resource_type, resource_id, role_id)
        WHERE tenant_id IS NULL AND role_id IS NOT NULL
    """,
]

# 存量平台资源回填给平台 admin/viewer，保持升级后可见性不变；superadmin 默认全量可见
_UPGRADE += [
    f"""
    INSERT INTO resource_grants (resource_type, resource_id, tenant_id, role_id)
    SELECT '{resource_type}', res.id, NULL, r.id
      FROM {table} res
     CROSS JOIN roles r
     WHERE res.tenant_id IS NULL
       AND r.tenant_id IS NULL
       AND r.code IN ('admin', 'viewer')
    ON CONFLICT DO NOTHING
    """
    for resource_type, table in _RESOURCE_TABLES
]

_DOWNGRADE = [
    # 平台授权与角色绑定无法映射回租户模型，回滚会丢失，请在预发库演练并备份
    "DELETE FROM resource_grants WHERE tenant_id IS NULL",
    "DROP INDEX IF EXISTS ux_resource_grants_platform_role",
    "ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS fk_resource_grants_role",
    "ALTER TABLE resource_grants DROP CONSTRAINT IF EXISTS ck_resource_grants_scope",
    "ALTER TABLE resource_grants ALTER COLUMN tenant_id SET NOT NULL",
    "DROP INDEX IF EXISTS ix_admin_users_role",
    "ALTER TABLE admin_users DROP COLUMN IF EXISTS role_id",
    "DROP INDEX IF EXISTS ux_roles_platform_name",
    "DROP INDEX IF EXISTS ux_roles_platform_code",
    "DELETE FROM roles WHERE tenant_id IS NULL",
    "ALTER TABLE roles ALTER COLUMN tenant_id SET NOT NULL",
]


def upgrade() -> None:
    """建立平台角色、账号绑定与平台资源授权。"""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """删除平台角色体系；平台角色绑定与授权不可恢复。"""
    for statement in _DOWNGRADE:
        op.execute(statement)
