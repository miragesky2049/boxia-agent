"""v4 租户用量账本：tenant_usage_ledger。

Revision ID: 0033_v4_usage_ledger
Revises: 0032_v4_model
Create Date: 2026-10-29

设计要点：
- 每次 LLM 节点调用写一条，记录 tenant / application / run / node 维度的 token 用量
- 计费订阅者从 NodeExecutionEvent 落库，不包中间件
- 与 run 表关联，可按时间、租户、应用聚合查询
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_v4_usage_ledger"
down_revision: str | None = "0032_v4_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_usage_ledger",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("application_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_usage_ledger_tenant_time",
        "tenant_usage_ledger",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_usage_ledger_run",
        "tenant_usage_ledger",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_table("tenant_usage_ledger")
