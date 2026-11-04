"""v4 运行实例：run + run_node_execution。

Revision ID: 0031_v4_run
Revises: 0030_v4_field_version
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_v4_run"
down_revision: str | None = "0030_v4_field_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 运行实例：每次 graph 执行的完整录像
    op.create_table(
        "run",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "graph_snapshot",
            postgresql.JSONB(),
            nullable=False,
            comment="运行时 graph 快照",
        ),
        sa.Column("input", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="running",
            comment="running / success / error / interrupted",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "langgraph_thread_id",
            sa.String(length=100),
            nullable=False,
            comment="LangGraph checkpointer thread_id，用于 time-travel",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'error', 'interrupted')",
            name="ck_run_status",
        ),
    )
    op.create_index("ix_run_tenant", "run", ["tenant_id", "started_at"])
    op.create_index("ix_run_app", "run", ["application_id", "started_at"])

    # 节点执行记录：每个节点的输入/输出/耗时
    op.create_table(
        "run_node_execution",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(length=100), nullable=False),
        sa.Column("node_type", sa.String(length=50), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=True),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_node_exec_run", "run_node_execution", ["run_id", "node_id"])


def downgrade() -> None:
    op.drop_table("run_node_execution")
    op.drop_table("run")
