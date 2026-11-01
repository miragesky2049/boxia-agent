"""v4_event_webhook：租户级 webhook 通知订阅。

Revision ID: 0035_v4_event_webhook
Revises: 0034_v4_usage_ledger_user
Create Date: 2026-10-29

设计要点：
- tenant_id 隔离，application_id 可空（空 = 该租户所有应用）
- event_type: run_finished / run_error / node_error
- url 由租户配置，GraphRunner 节点事件触发时异步 POST
- is_enabled 软开关，失败不阻塞主流程
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_v4_event_webhook"
down_revision: str | None = "0034_v4_usage_ledger_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "v4_event_webhook",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("application_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_v4_event_webhook_tenant_event",
        "v4_event_webhook",
        ["tenant_id", "event_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_v4_event_webhook_tenant_event", table_name="v4_event_webhook")
    op.drop_table("v4_event_webhook")
