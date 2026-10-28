"""v4 租户实例：tenant_application_instance + 配置层叠。

Revision ID: 0029_v4_tenant_instance
Revises: 0028_v4_core
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_v4_instance"
down_revision: str | None = "0028_v4_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_application_instance",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
            comment="active / suspended / disabled / revoked",
        ),
        sa.Column(
            "source",
            sa.String(length=20),
            nullable=False,
            server_default="marketplace",
            comment="marketplace / granted",
        ),
        sa.Column(
            "overrides",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="字段级覆盖: {path: {value, applied_at_version, frozen, freeze_reason}}",
        ),
        sa.Column(
            "pinned_version",
            sa.Integer(),
            nullable=True,
            comment="锁定版本，NULL=跟随最新",
        ),
        sa.Column("granted_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'disabled', 'revoked')",
            name="ck_instance_status",
        ),
        sa.CheckConstraint(
            "source IN ('marketplace', 'granted')",
            name="ck_instance_source",
        ),
        sa.UniqueConstraint("tenant_id", "application_id", name="ux_instance_unique"),
    )
    op.create_index(
        "ix_instance_tenant", "tenant_application_instance", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_instance_app", "tenant_application_instance", ["application_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("tenant_application_instance")
