"""严格 RBAC：为存量零授权租户自有资源回填角色授权

Revision ID: 0009_strict_rbac_grants
Revises: 0008_admin_users_platform_only
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_strict_rbac_grants"
down_revision: str | None = "0008_admin_users_platform_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 只回填完全没有授权记录的租户自有资源，避免把已按角色收窄的资源放大给全部角色。
_UPGRADE = [
    """
    INSERT INTO resource_grants (resource_type, resource_id, tenant_id, role_id)
    SELECT 'agent', a.id, a.tenant_id, r.id
      FROM agents a
      JOIN roles r ON r.tenant_id = a.tenant_id
     WHERE a.tenant_id IS NOT NULL
       AND NOT EXISTS (
            SELECT 1 FROM resource_grants g
             WHERE g.resource_type = 'agent' AND g.resource_id = a.id
       )
    ON CONFLICT DO NOTHING
    """,
    *[
        f"""
    INSERT INTO resource_grants (resource_type, resource_id, tenant_id, role_id)
    SELECT '{resource_type}', res.id, res.tenant_id, r.id
      FROM {table} res
      JOIN roles r ON r.tenant_id = res.tenant_id
     WHERE res.tenant_id IS NOT NULL
       AND NOT EXISTS (
            SELECT 1 FROM resource_grants g
             WHERE g.resource_type = '{resource_type}' AND g.resource_id = res.id
       )
    ON CONFLICT DO NOTHING
    """
        for resource_type, table in (
            ("skill", "skills"),
            ("tool", "tools"),
            ("component", "components"),
            ("prompt", "prompts"),
        )
    ],
]

_DOWNGRADE: list[str] = []


def upgrade() -> None:
    """回填存量资源授权；重复执行幂等。"""
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    """不自动删除回填授权：无法可靠区分存量与人工授权，回滚前请备份 resource_grants。"""
