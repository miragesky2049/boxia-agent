"""0047 tenant_settings：租户级默认模型 + 插件白名单。

Revision ID: 0047_tenant_settings
Revises: 0046_published_graph_version
Create Date: 2026-10-31

设计要点：
- 一行一租户，kv 风格 JSONB；未配置时所有字段为空
- default_model_catalog_id：租户默认使用的 model_catalog.id（画布新建 llm 节点时的默认值）
- allowed_catalog_ids：允许该租户可见的模型白名单（UUID 列表；空 = 平台全量可见）
- plugin_whitelist：允许该租户调用的工具名白名单（字符串列表；空 = 平台全量可见）
- 实际 enforce 在运行时按 model_service / tool_executor 集成（T16 阶段先落库 + admin 页面）
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0047_tenant_settings"
down_revision: str | None = "0046_published_graph_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "default_model_catalog_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("model_catalog.id", ondelete="SET NULL"),
            nullable=True,
            comment="租户默认模型 model_catalog.id；NULL 表示走平台默认",
        ),
        sa.Column(
            "allowed_catalog_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="允许该租户可见的模型 catalog UUID 列表；空数组 = 平台全量可见",
        ),
        sa.Column(
            "plugin_whitelist",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="允许该租户调用的工具名白名单；空数组 = 平台全量可见",
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
    )


def downgrade() -> None:
    op.drop_table("tenant_settings")
