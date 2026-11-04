"""event_webhook：去掉表名 v4 前缀。

Revision ID: 0036_rename_event_webhook
Revises: 0035_v4_event_webhook
Create Date: 2026-10-29

设计要点：
- 表名 v4_event_webhook -> event_webhook，去掉用户不理解的版本前缀
- 列结构不变，仅 rename 表
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036_rename_event_webhook"
down_revision: str | None = "0035_v4_event_webhook"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("v4_event_webhook", "event_webhook")
    # 索引名也一并改，保持命名一致
    op.execute("ALTER INDEX ix_v4_event_webhook_tenant_event RENAME TO ix_event_webhook_tenant_event")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_event_webhook_tenant_event RENAME TO ix_v4_event_webhook_tenant_event")
    op.rename_table("event_webhook", "v4_event_webhook")
