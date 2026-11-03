"""0060 表重命名：resource_grant → tenant_resource_entitlement（P3-4）。

Revision ID: 0060_tenant_resource_entitlement
Revises: 0059_entitlement_plan
Create Date: 2026-11-03

设计要点：
- 表语义是"租户对资源的权益行"，原名与角色授权复数表 resource_grants 极易混淆，改名收口口径。
- 约束/索引名随表同步更名，避免遗留 resource_grant_* 前缀误导运维查询。
- 保留同名兼容视图 resource_grant 一个发布周期：简单单表视图在 PG 下可读写，
  兜底尚未切流的旁路查询；下一迭代 contract 阶段删除。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0060_tenant_resource_entitlement"
down_revision: str | None = "0059_entitlement_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = "tenant_resource_entitlement"
_RENAMES = [
    ("resource_grant_pkey", "tenant_resource_entitlement_pkey"),
    ("ux_resource_grant_unique", "ux_tenant_resource_entitlement_unique"),
    ("resource_grant_resource_id_fkey", "tenant_resource_entitlement_resource_id_fkey"),
    ("resource_grant_tenant_id_fkey", "tenant_resource_entitlement_tenant_id_fkey"),
    ("ck_resource_grant_status", "ck_tenant_resource_entitlement_status"),
    ("ck_resource_grant_source", "ck_tenant_resource_entitlement_source"),
    ("ck_resource_grant_type", "ck_tenant_resource_entitlement_type"),
]
_INDEX_RENAMES = [
    ("ix_resource_grant_tenant_status", "ix_tenant_resource_entitlement_tenant_status"),
    ("ix_resource_grant_tenant", "ix_tenant_resource_entitlement_tenant"),
]


def upgrade() -> None:
    op.execute("ALTER TABLE resource_grant RENAME TO tenant_resource_entitlement")
    # RENAME CONSTRAINT 会连带重命名 pkey/unique 背后的索引，无需单独 ALTER INDEX
    for old, new in _RENAMES:
        op.execute(f"ALTER TABLE {_NEW} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")
    op.execute("CREATE VIEW resource_grant AS SELECT * FROM tenant_resource_entitlement")
    op.execute(
        "COMMENT ON VIEW resource_grant IS "
        "'兼容视图（P3-4）：实体表已更名 tenant_resource_entitlement，保留一个发布周期后删除'"
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS resource_grant")
    for old, new in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for old, new in _RENAMES:
        op.execute(f"ALTER TABLE {_NEW} RENAME CONSTRAINT {new} TO {old}")
    op.execute("ALTER TABLE tenant_resource_entitlement RENAME TO resource_grant")
