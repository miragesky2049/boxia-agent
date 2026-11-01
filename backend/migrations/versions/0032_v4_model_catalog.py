"""v4 模型目录：model_provider + model_catalog。

Revision ID: 0032_v4_model_catalog
Revises: 0031_v4_run
Create Date: 2026-10-28

设计要点：
- 产品级配置 model_provider（base_url + api_key），租户 LLM 节点通过 model_id 引用
- model_catalog 记录模型元数据（能力、上下文窗口、是否支持工具调用）
- 阶段二：租户自带 API key（owner_type=tenant）预留，当前仅 platform
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_v4_model"
down_revision: str | None = "0031_v4_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========== model_provider ==========
    op.create_table(
        "model_provider",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False, comment="例如 deepseek / qwen"),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column(
            "api_key",
            sa.String(length=500),
            nullable=False,
            server_default="",
            comment="平台统一凭据；阶段二支持租户自带 key",
        ),
        sa.Column(
            "owner_type",
            sa.String(length=20),
            nullable=False,
            server_default="platform",
            comment="platform / tenant（tenant 预留）",
        ),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "owner_type IN ('platform', 'tenant')",
            name="ck_model_provider_owner_type",
        ),
    )

    # ========== model_catalog ==========
    op.create_table(
        "model_catalog",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "provider_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("model_provider.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_id",
            sa.String(length=100),
            nullable=False,
            comment="对外引用的模型 ID，例如 deepseek-chat",
        ),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column(
            "capabilities",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="{supports_tools, supports_vision, context_window, max_output_tokens}",
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("model_id", name="ux_model_catalog_model_id"),
    )
    op.create_index("ix_model_catalog_provider", "model_catalog", ["provider_id"])


def downgrade() -> None:
    op.drop_table("model_catalog")
    op.drop_table("model_provider")
