"""v4 核心表：application / application_graph / resource / resource_grant。

Revision ID: 0028_v4_application_graph_resource
Revises: 0027_tool_menu_permissions
Create Date: 2026-10-28

v4 重构要点：
- 废弃 PLATFORM_TENANT_ID 隐式约定，改为显式 owner_type / owner_id
- 合并 agents + workflows 为统一 application，graph 存运行时定义
- tool / prompt / skill / knowledge 统一为 resource 表
- 资源可见性通过 resource_grant 表管理
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_v4_core"
down_revision: str | None = "0027_tool_menu_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========== application（替代 agents + workflows） ==========
    op.create_table(
        "application",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_type",
            sa.String(length=20),
            nullable=False,
            comment="platform / tenant",
        ),
        sa.Column(
            "owner_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
            comment="owner_type=platform 时为 NULL",
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_listed_in_market",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="是否出现在应用市场",
        ),
        sa.Column(
            "visibility_mode",
            sa.String(length=20),
            nullable=False,
            server_default="all",
            comment="all / custom",
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
            "owner_type IN ('platform', 'tenant')",
            name="ck_application_owner_type",
        ),
        sa.CheckConstraint(
            "visibility_mode IN ('all', 'custom')",
            name="ck_application_visibility_mode",
        ),
    )
    op.create_index("ix_application_owner", "application", ["owner_type", "owner_id"])
    op.create_index(
        "ix_application_market",
        "application",
        ["is_listed_in_market"],
        postgresql_where=sa.text("is_listed_in_market = true"),
    )

    # ========== application_graph（统一 graph 定义） ==========
    op.create_table(
        "application_graph",
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "graph",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="LangGraph 兼容的 nodes + edges 定义",
        ),
        sa.Column(
            "graph_schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column(
            "runtime_mode",
            sa.String(length=20),
            nullable=False,
            server_default="dag",
            comment="dag / agent_loop，运行时自动推断",
        ),
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
            "runtime_mode IN ('dag', 'agent_loop')",
            name="ck_application_graph_runtime_mode",
        ),
    )

    # ========== resource（统一 tool / prompt / skill / knowledge） ==========
    op.create_table(
        "resource",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "type",
            sa.String(length=40),
            nullable=False,
            comment="tool / prompt / skill / knowledge",
        ),
        sa.Column(
            "owner_type",
            sa.String(length=20),
            nullable=False,
            comment="platform / tenant",
        ),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "is_deprecated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="废弃而非物理删除",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('tool', 'prompt', 'skill', 'knowledge')",
            name="ck_resource_type",
        ),
        sa.CheckConstraint(
            "owner_type IN ('platform', 'tenant')",
            name="ck_resource_owner_type",
        ),
    )
    op.create_index("ix_resource_owner", "resource", ["owner_type", "owner_id"])
    op.create_index("ix_resource_type", "resource", ["type"])
    op.create_index(
        "ix_resource_active",
        "resource",
        ["type", "is_enabled", "is_deprecated"],
        postgresql_where=sa.text("is_enabled = true AND is_deprecated = false"),
    )

    # ========== resource_grant（产品级资源开放给租户） ==========
    op.create_table(
        "resource_grant",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "resource_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("resource.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("resource_id", "tenant_id", name="ux_resource_grant_unique"),
    )
    op.create_index("ix_resource_grant_tenant", "resource_grant", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("resource_grant")
    op.drop_table("resource")
    op.drop_table("application_graph")
    op.drop_table("application")
