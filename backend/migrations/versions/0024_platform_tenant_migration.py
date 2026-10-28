"""产品级租户统一迁移：tenant_id IS NULL → PLATFORM_TENANT_ID（全零 UUID）。

历史上产品级资源 / 平台角色 / 平台授权一律用 tenant_id IS NULL 表示；
本迁移把全部老数据规整为 PLATFORM_TENANT_ID（全零 UUID），并把相关列改为 NOT NULL。
同时重建基于 tenant_id 谓词的部分唯一索引，以及 agents 表的产品级/租户级 check 约束。

Revision ID: 0024_platform_tenant_migration
Revises: 0023_document_chunks_metadata
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_platform_tenant_migration"
down_revision: str | None = "0023_document_chunks_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 产品级租户 ID（全零 UUID）
PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# 历史上 tenant_id IS NULL 的表（迁移前为 NULL 表示产品级）。
# agent_tools / agent_skills 是关联表，从来没有 tenant_id 列，不在此列。
_NULLABLE_TABLES = (
    "agents",
    "skills",
    "tools",
    "components",
    "prompts",
    "documents",
    "document_chunks",
    "audit_logs",
    "roles",
    "resource_grants",
)


def upgrade() -> None:
    """1) 先插入平台租户行；2) 回填 NULL；3) 改为 NOT NULL；4) 重建索引与约束。"""
    # 1. 先种入产品级平台租户，避免外键 tenants.id 约束失败。
    op.execute(
        f"""
        INSERT INTO tenants (id, code, name, is_active)
        VALUES ('{PLATFORM_TENANT_ID}', 'platform', '产品级平台', TRUE)
        ON CONFLICT (id) DO NOTHING
        """
    )

    # 2. 把历史 NULL 行回填为 PLATFORM_TENANT_ID。
    for table in _NULLABLE_TABLES:
        op.execute(
            f"UPDATE {table} SET tenant_id = '{PLATFORM_TENANT_ID}' WHERE tenant_id IS NULL"
        )

    # 3. 逐表断言无残留 NULL，再 SET NOT NULL。
    for table in _NULLABLE_TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN tenant_id SET NOT NULL"
        )

    # 4. 重建部分唯一索引：旧谓词是 tenant_id IS NULL，新谓词是 tenant_id = PLATFORM_TENANT_ID。
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_code")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_roles_platform_code
            ON roles (lower(code))
            WHERE tenant_id = '{PLATFORM_TENANT_ID}'
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_name")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_roles_platform_name
            ON roles (lower(name))
            WHERE tenant_id = '{PLATFORM_TENANT_ID}'
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_resource_grants_platform_role")
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_resource_grants_platform_role
            ON resource_grants (resource_type, resource_id, role_id)
            WHERE tenant_id = '{PLATFORM_TENANT_ID}' AND role_id IS NOT NULL
        """
    )

    # 5. agents 表的两个 check 约束：旧谓词用 tenant_id IS NULL 表示平台，
    #    现在统一为 tenant_id = PLATFORM_TENANT_ID 表示平台。
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_platform_no_dept"
    )
    op.execute(
        f"""
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_platform_no_dept
            CHECK (tenant_id <> '{PLATFORM_TENANT_ID}' OR department_id IS NULL)
        """
    )
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_tenant_dept_required"
    )
    op.execute(
        f"""
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_tenant_dept_required
            CHECK (tenant_id = '{PLATFORM_TENANT_ID}' OR department_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    """回滚：恢复老的 NULL 语义。

    回滚是有损的：PLATFORM_TENANT_ID 的数据会被标回 NULL；租户 ID 行不动。
    """
    # 1. 删除新约束与索引，重建旧谓词。
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_tenant_dept_required"
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_tenant_dept_required
            CHECK (tenant_id IS NULL OR department_id IS NOT NULL)
        """
    )
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS ck_agents_platform_no_dept"
    )
    op.execute(
        """
        ALTER TABLE agents
            ADD CONSTRAINT ck_agents_platform_no_dept
            CHECK (tenant_id IS NOT NULL OR department_id IS NULL)
        """
    )

    op.execute("DROP INDEX IF EXISTS ux_resource_grants_platform_role")
    op.execute(
        """
        CREATE UNIQUE INDEX ux_resource_grants_platform_role
            ON resource_grants (resource_type, resource_id, role_id)
            WHERE tenant_id IS NULL AND role_id IS NOT NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_name")
    op.execute(
        """
        CREATE UNIQUE INDEX ux_roles_platform_name
            ON roles (lower(name))
            WHERE tenant_id IS NULL
        """
    )
    op.execute("DROP INDEX IF EXISTS ux_roles_platform_code")
    op.execute(
        """
        CREATE UNIQUE INDEX ux_roles_platform_code
            ON roles (lower(code))
            WHERE tenant_id IS NULL
        """
    )

    # 2. 放开 NOT NULL。
    for table in _NULLABLE_TABLES:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN tenant_id DROP NOT NULL"
        )

    # 3. 把 PLATFORM_TENANT_ID 的行标回 NULL。
    for table in _NULLABLE_TABLES:
        op.execute(
            f"UPDATE {table} SET tenant_id = NULL WHERE tenant_id = '{PLATFORM_TENANT_ID}'"
        )

    # 4. 删除平台租户行。
    op.execute(f"DELETE FROM tenants WHERE id = '{PLATFORM_TENANT_ID}'")
