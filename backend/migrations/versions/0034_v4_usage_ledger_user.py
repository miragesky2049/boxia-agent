"""tenant_usage_ledger 加 user_id：标记单次用量由哪个最终用户触发。

Revision ID: 0034_v4_usage_ledger_user
Revises: 0033_v4_usage_ledger
Create Date: 2026-10-29

设计要点：
- 可空：历史数据回填 NULL，未来由 GraphRunner 从 AdminPrincipal 注入
- 便于按用户聚合用量 / 做用户级配额
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_v4_usage_ledger_user"
down_revision: str | None = "0033_v4_usage_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_usage_ledger",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_usage_ledger_user_time",
        "tenant_usage_ledger",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_ledger_user_time", table_name="tenant_usage_ledger")
    op.drop_column("tenant_usage_ledger", "user_id")
