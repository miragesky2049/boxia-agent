"""0076 conversation 摘要水位线列（M4 PRD F15.2：摘要式记忆）。

背景（docs/agent-m4-prd.md F15）：
- 短期记忆 strategy=summarize 时，超出保留窗口的旧消息不直接丢弃，增量总结为
  摘要段注入上下文；摘要正文与水位线持久化在 conversation 行上，
  **不落 message 表**（防污染消息面与前端历史渲染）；
- summary_through_message_id 指向"摘要已覆盖到"的那条消息，其后的消息按原文
  进上下文；回写走乐观并发（UPDATE ... WHERE 水位线 IS NOT DISTINCT FROM 旧值），
  因此不建外键——message 清空/物理删除不应被摘要引用锁住，水位线悬空由
  plan_summarization 按"找不到该条消息则整体重算"兜底。
存量行不受影响：三列均可空。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076_conversation_summary"
down_revision: str | None = "0075_run_parent_and_cancelled"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation",
        sa.Column("summary", sa.Text(), nullable=True, comment="更早对话的摘要正文（M4 PRD F15.2）"),
    )
    op.add_column(
        "conversation",
        sa.Column(
            "summary_through_message_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
            comment="摘要水位线：已覆盖到的消息 ID，其后消息按原文进上下文",
        ),
    )
    op.add_column(
        "conversation",
        sa.Column(
            "summary_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="摘要最近一次回写时间（频控与排障用）",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation", "summary_updated_at")
    op.drop_column("conversation", "summary_through_message_id")
    op.drop_column("conversation", "summary")
