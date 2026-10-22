"""multi tenant：租户表、tenant_id 行级隔离与按范围唯一约束

Revision ID: 0004_multi_tenant
Revises: 0003_search_trgm
Create Date: 2026-10-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0004_multi_tenant"
down_revision: str | None = "0003_search_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = ("admin_users", "agents", "skills", "tools", "components", "prompts")
_RESOURCE_INDEXES = {
    "agents": "ux_agents_name_lower",
    "skills": "ux_skills_name_lower",
    "tools": "ux_tools_name_lower",
    "components": "ux_components_name_lower",
    "prompts": "ux_prompts_name_lower",
}

_UPGRADE = [
    """
    CREATE TABLE tenants (
        id          BIGSERIAL PRIMARY KEY,
        code        VARCHAR(63)  NOT NULL UNIQUE,
        name        VARCHAR(100) NOT NULL,
        is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
        created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
        CONSTRAINT ck_tenants_code CHECK (code = lower(code))
    )
    """,
    """
    CREATE TRIGGER trg_tenants_updated_at BEFORE UPDATE ON tenants
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
]

# 既有数据 tenant_id 为空，自动归为产品级资源/产品级账号。
for _table in _TENANT_TABLES:
    _UPGRADE.append(
        f"ALTER TABLE {_table} ADD COLUMN tenant_id BIGINT REFERENCES tenants(id) "
        "ON DELETE RESTRICT"
    )

_UPGRADE += [
    "ALTER TABLE audit_logs ADD COLUMN tenant_id BIGINT REFERENCES tenants(id) ON DELETE SET NULL",
    "CREATE INDEX ix_admin_users_tenant ON admin_users (tenant_id)",
    "CREATE INDEX ix_agents_tenant      ON agents (tenant_id)",
    "CREATE INDEX ix_skills_tenant      ON skills (tenant_id)",
    "CREATE INDEX ix_tools_tenant       ON tools (tenant_id)",
    "CREATE INDEX ix_components_tenant  ON components (tenant_id)",
    "CREATE INDEX ix_prompts_tenant     ON prompts (tenant_id)",
    "CREATE INDEX ix_audit_logs_tenant  ON audit_logs (tenant_id, created_at DESC)",
    "ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS admin_users_username_key",
    "DROP INDEX IF EXISTS ux_admin_users_username",
    # 同一租户内用户名唯一；产品级账号（tenant_id 为 NULL）之间唯一。
    "CREATE UNIQUE INDEX ux_admin_users_tenant_username "
    "ON admin_users (COALESCE(tenant_id, 0), username)",
]

for _table, _index in _RESOURCE_INDEXES.items():
    _UPGRADE.append(f"DROP INDEX IF EXISTS {_index}")
    _UPGRADE.append(
        f"CREATE UNIQUE INDEX {_index} ON {_table} (COALESCE(tenant_id, 0), lower(name))"
    )

_DOWNGRADE = [
    "DROP INDEX IF EXISTS ux_admin_users_tenant_username",
    "DROP INDEX IF EXISTS ux_agents_name_lower",
    "DROP INDEX IF EXISTS ux_skills_name_lower",
    "DROP INDEX IF EXISTS ux_tools_name_lower",
    "DROP INDEX IF EXISTS ux_components_name_lower",
    "DROP INDEX IF EXISTS ux_prompts_name_lower",
    "CREATE UNIQUE INDEX ux_agents_name_lower     ON agents (lower(name))",
    "CREATE UNIQUE INDEX ux_skills_name_lower     ON skills (lower(name))",
    "CREATE UNIQUE INDEX ux_tools_name_lower      ON tools (lower(name))",
    "CREATE UNIQUE INDEX ux_components_name_lower ON components (lower(name))",
    "CREATE UNIQUE INDEX ux_prompts_name_lower    ON prompts (lower(name))",
    "ALTER TABLE admin_users ADD CONSTRAINT admin_users_username_key UNIQUE (username)",
    "DROP INDEX IF EXISTS ix_admin_users_tenant",
    "DROP INDEX IF EXISTS ix_agents_tenant",
    "DROP INDEX IF EXISTS ix_skills_tenant",
    "DROP INDEX IF EXISTS ix_tools_tenant",
    "DROP INDEX IF EXISTS ix_components_tenant",
    "DROP INDEX IF EXISTS ix_prompts_tenant",
    "DROP INDEX IF EXISTS ix_audit_logs_tenant",
    "ALTER TABLE audit_logs DROP COLUMN IF EXISTS tenant_id",
]

for _table in reversed(_TENANT_TABLES):
    _DOWNGRADE.append(f"ALTER TABLE {_table} DROP COLUMN IF EXISTS tenant_id")

_DOWNGRADE += [
    "DROP TRIGGER IF EXISTS trg_tenants_updated_at ON tenants",
    "DROP TABLE IF EXISTS tenants",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
