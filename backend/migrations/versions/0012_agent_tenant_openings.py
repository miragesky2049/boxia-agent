"""智能体开通关系：平台智能体按租户开通/关闭

Revision ID: 0012_agent_tenant_openings
Revises: 0011_rbac_permission_resources
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_agent_tenant_openings"
down_revision: str | None = "0011_rbac_permission_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建开通表，并把存量平台智能体授权回填为已开通关系。"""
    op.execute(
        """
        CREATE TABLE agent_tenant_openings (
            id         BIGSERIAL   PRIMARY KEY,
            agent_id   BIGINT      NOT NULL
                REFERENCES agents (id) ON DELETE CASCADE,
            tenant_id  BIGINT      NOT NULL
                REFERENCES tenants (id) ON DELETE CASCADE,
            opened_by  BIGINT      REFERENCES admin_users (id) ON DELETE SET NULL,
            opened_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_agent_tenant_openings UNIQUE (agent_id, tenant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_agent_tenant_openings_tenant "
        "ON agent_tenant_openings (tenant_id, agent_id)"
    )
    # 存量数据以授权记录为准：存在任一租户授权的平台智能体即视为已开通
    op.execute(
        """
        INSERT INTO agent_tenant_openings (agent_id, tenant_id)
        SELECT DISTINCT rg.resource_id, rg.tenant_id
        FROM resource_grants rg
        JOIN agents a ON a.id = rg.resource_id
        WHERE rg.resource_type = 'agent'
          AND rg.tenant_id IS NOT NULL
          AND a.tenant_id IS NULL
        ON CONFLICT (agent_id, tenant_id) DO NOTHING
        """
    )


def downgrade() -> None:
    """删除开通关系；授权数据不受影响。"""
    op.drop_index("ix_agent_tenant_openings_tenant", table_name="agent_tenant_openings")
    op.drop_table("agent_tenant_openings")
