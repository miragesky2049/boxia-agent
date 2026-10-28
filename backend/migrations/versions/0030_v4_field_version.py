"""v4 字段级版本：application_field_version + tenant_field_pin。

Revision ID: 0030_v4_field_version
Revises: 0029_v4_instance
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_v4_field_version"
down_revision: str | None = "0029_v4_instance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 字段级版本：每个字段独立版本历史
    op.create_table(
        "application_field_version",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "field_path",
            sa.String(length=500),
            nullable=False,
            comment="graph.nodes.llm_1.config.temperature",
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "application_id", "field_path", "version", name="ux_field_version_unique"
        ),
    )
    op.create_index(
        "ix_field_version_app", "application_field_version", ["application_id", "field_path"]
    )

    # 租户字段 pin：租户锁定某个字段在某个版本
    op.create_table(
        "tenant_field_pin",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_path", sa.String(length=500), nullable=False),
        sa.Column("pinned_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "application_id", "field_path", name="ux_field_pin_unique"
        ),
    )
    op.create_index("ix_field_pin_tenant", "tenant_field_pin", ["tenant_id", "application_id"])


def downgrade() -> None:
    op.drop_table("tenant_field_pin")
    op.drop_table("application_field_version")
