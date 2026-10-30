"""0042 graph 整图版本 + 租户 config kv + marketplace 索引。

Revision ID: 0042_graph_version
Revises: 0041_business_comments
Create Date: 2026-10-30

设计要点（对齐 coze / dify / n8n 行业方案）：
- application_graph_version：每次 save_graph 写一行整图快照，替代字段级 diff
- tenant_application_instance.pinned_graph_version：租户 pin 整图版本
- tenant_application_config：租户级 kv 配置覆盖（key=graph.nodes.{id}.config.{field}）
- marketplace 部分覆盖索引，cursor 分页
- 旧表 application_field_version / tenant_field_pin 保留（不 drop），仅停止写入
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042_graph_version"
down_revision: str | None = "0041_business_comments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========== 1. application_graph_version：整图版本历史 ==========
    op.create_table(
        "application_graph_version",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "application_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "graph",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="整图快照（LangGraph 兼容的 nodes + edges）",
        ),
        sa.Column(
            "runtime_mode",
            sa.String(length=20),
            nullable=False,
            server_default="dag",
        ),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("application_id", "version", name="ux_graph_version_app_ver"),
    )
    op.create_index(
        "ix_graph_version_app",
        "application_graph_version",
        ["application_id", sa.text("version DESC")],
    )

    # ========== 2. tenant_application_instance 加 pinned_graph_version ==========
    op.add_column(
        "tenant_application_instance",
        sa.Column(
            "pinned_graph_version",
            sa.Integer(),
            nullable=True,
            comment="租户锁定的整图版本；NULL 表示跟随 latest",
        ),
    )

    # ========== 3. tenant_application_config：租户级 kv 配置覆盖 ==========
    op.create_table(
        "tenant_application_config",
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
        sa.Column("config_key", sa.String(length=255), nullable=False,
                  comment="形如 graph.nodes.{node_id}.config.{field}"),
        sa.Column("config_value", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "application_id", "config_key",
            name="ux_tenant_app_config_key",
        ),
    )
    op.create_index(
        "ix_tenant_app_config_lookup",
        "tenant_application_config",
        ["tenant_id", "application_id"],
    )

    # ========== 4. marketplace 部分覆盖索引 ==========
    op.execute(
        "CREATE INDEX ix_market_listing ON application (updated_at DESC) "
        "INCLUDE (id, name, avatar_url, description) "
        "WHERE owner_type = 'platform' AND is_enabled = true AND is_listed_in_market = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_market_listing")
    op.drop_table("tenant_application_config")
    op.drop_column("tenant_application_instance", "pinned_graph_version")
    op.drop_index("ix_graph_version_app", table_name="application_graph_version")
    op.drop_table("application_graph_version")
