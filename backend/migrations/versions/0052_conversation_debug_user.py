"""0052 conversation 放开 user_id 外键：试运行会话归属管理员账号。

Revision ID: 0052_conversation_debug_user
Revises: 0051_application_variables
Create Date: 2026-11-02

设计要点：
- channel='debug' 的会话由 admin 画布试运行创建，user_id 存 admin_users.id；
  原 fk_conversation_user 只认 users，导致试运行建会话必然外键冲突
- 归属改由应用层按 tenant_id + channel 过滤，与项目内其他引用 admin_users 的表
  （admin_refresh_tokens 之外如审计日志）保持同样做法
- downgrade 需先清空 channel='debug' 的会话，否则恢复外键会失败
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0052_conversation_debug_user"
down_revision: str | None = "0051_application_variables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_conversation_user", "conversation", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "fk_conversation_user",
        "conversation",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
