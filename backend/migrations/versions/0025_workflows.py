"""工作流：workflows / workflow_templates 表。

Revision ID: 0025_workflows
Revises: 0024_platform_tenant_migration
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_workflows"
down_revision: str | None = "0024_platform_tenant_migration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 产品级租户 ID（全零 UUID）；workflows / workflow_templates 直接以 NOT NULL 建表
PLATFORM_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    """创建 workflows 与 workflow_templates 表，tenant_id 一律 NOT NULL。"""
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "graph",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "visibility_mode",
            sa.String(length=16),
            nullable=False,
            server_default="all",
        ),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
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
            "visibility_mode IN ('all', 'custom')",
            name="ck_workflows_visibility_mode",
        ),
    )
    op.create_index(
        "ix_workflows_tenant_created_by", "workflows", ["tenant_id", "created_by"]
    )
    # 同一租户下工作流名称唯一（租户管理员视角）
    op.create_index(
        "ux_workflows_tenant_name",
        "workflows",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )

    # 模板表：仅产品级（PLATFORM_TENANT_ID）使用；租户通过 clone 复制为自身 workflows。
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            server_default=PLATFORM_TENANT_ID,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "graph",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("category", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        # 模板只允许挂在产品级租户下
        sa.CheckConstraint(
            f"tenant_id = '{PLATFORM_TENANT_ID}'",
            name="ck_workflow_templates_platform_only",
        ),
    )
    op.create_index(
        "ux_workflow_templates_platform_name",
        "workflow_templates",
        [sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    """回滚：删除两张表。"""
    op.drop_index(
        "ux_workflow_templates_platform_name", table_name="workflow_templates"
    )
    op.drop_table("workflow_templates")
    op.drop_index("ux_workflows_tenant_name", table_name="workflows")
    op.drop_index("ix_workflows_tenant_created_by", table_name="workflows")
    op.drop_table("workflows")
