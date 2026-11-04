"""0040 应用授权 MVP：application 加字段 + tenant_application_instance 加字段 + 新建 application_apply。

Revision ID: 0040_application_auth
Revises: 0039_app_visibility
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_application_auth"
down_revision: str | None = "0039_app_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========== application 表加字段 ==========
    op.add_column(
        "application",
        sa.Column("sale_mode", sa.Integer(), nullable=False, server_default="1",
                  comment="1=仅运营后台开通；2=市场可见+可申请"),
    )
    op.add_column(
        "application",
        sa.Column("support_trial", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "application",
        sa.Column("doc_url", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column(
        "application",
        sa.Column("ext_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )

    # ========== tenant_application_instance 表加字段 ==========
    op.add_column(
        "tenant_application_instance",
        sa.Column("auth_source", sa.String(length=20), nullable=False, server_default="OPS",
                  comment="OPS=运营直接开通；MARKET_APPLY=市场申请单关联开通"),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="FORMAL",
                  comment="FORMAL / TRIAL / GIFT"),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("contract_no", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("quota_json", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("expire_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("apply_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tenant_application_instance",
        sa.Column("remark", sa.Text(), nullable=False, server_default=""),
    )

    # 给 apply_id 加索引
    op.create_index(
        "ix_instance_apply",
        "tenant_application_instance",
        ["apply_id"],
    )

    # ========== 新建 application_apply 表 ==========
    op.create_table(
        "application_apply",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("apply_type", sa.String(length=20), nullable=False,
                  comment="TRIAL / BUY"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="SUBMITTED",
                  comment="SUBMITTED / HANDLING / PASS / REJECT / FINISH"),
        sa.Column("expect_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("contact", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("sales_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("audit_msg", sa.Text(), nullable=False, server_default=""),
        sa.Column("contract_no", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "apply_type IN ('TRIAL', 'BUY')",
            name="ck_apply_type",
        ),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'HANDLING', 'PASS', 'REJECT', 'FINISH')",
            name="ck_apply_status",
        ),
    )

    # 申请单索引
    op.create_index("ix_apply_tenant", "application_apply", ["tenant_id", "status"])
    op.create_index("ix_apply_app", "application_apply", ["application_id", "status"])
    op.create_index("ix_apply_sales", "application_apply", ["sales_user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_apply_sales", table_name="application_apply")
    op.drop_index("ix_apply_app", table_name="application_apply")
    op.drop_index("ix_apply_tenant", table_name="application_apply")
    op.drop_table("application_apply")

    op.drop_index("ix_instance_apply", table_name="tenant_application_instance")
    op.drop_column("tenant_application_instance", "remark")
    op.drop_column("tenant_application_instance", "apply_id")
    op.drop_column("tenant_application_instance", "expire_time")
    op.drop_column("tenant_application_instance", "start_time")
    op.drop_column("tenant_application_instance", "quota_json")
    op.drop_column("tenant_application_instance", "contract_no")
    op.drop_column("tenant_application_instance", "auth_type")
    op.drop_column("tenant_application_instance", "auth_source")

    op.drop_column("application", "ext_json")
    op.drop_column("application", "doc_url")
    op.drop_column("application", "support_trial")
    op.drop_column("application", "sale_mode")
