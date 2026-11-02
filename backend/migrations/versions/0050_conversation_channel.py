"""0050 conversation 加 channel：隔离画布调试会话与用户线上会话。

Revision ID: 0050_conversation_channel
Revises: 0049_application_flow_type
Create Date: 2026-11-02

设计要点：
- channel='api' 为用户端真实会话，'debug' 为 admin 画布试运行会话
- 用户端会话列表只查 api，避免调试数据污染
- 存量会话默认 api，行为不变
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_conversation_channel"
down_revision: str | None = "0049_application_flow_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default="api",
            comment="api（用户会话） / debug（画布试运行）",
        ),
    )
    op.create_check_constraint(
        "ck_conversation_channel",
        "conversation",
        "channel IN ('api', 'debug')",
    )
    op.create_index(
        "ix_conversation_channel_user",
        "conversation",
        ["tenant_id", "user_id", "channel", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_channel_user", table_name="conversation")
    op.drop_constraint("ck_conversation_channel", "conversation", type_="check")
    op.drop_column("conversation", "channel")
