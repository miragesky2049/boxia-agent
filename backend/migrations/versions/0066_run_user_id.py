"""run 增加发起人 user_id 与中断快照 interrupt_payload，支撑用户端工作流运行历史与人审列表。

Revision ID: 0066_run_user_id
Revises: 0065_users_role_optional
Create Date: 2026-11-05

背景：
- 用户端工作流（workflow）应用上线，需要按发起人查询「我的运行」；run 表自 0031 建表起没有 user_id。
- 人审中断 payload 此前只存在 LangGraph checkpointer 中，待审批列表无法用 SQL 直接获取，
  新增 interrupt_payload JSONB 冗余列，中断时写入、流转终态时清空。
- 历史数据两列均为 NULL：管理端旧运行记录不受影响，用户端历史只展示迁移后的新运行。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0066_run_user_id"
down_revision: str | None = "0065_users_role_optional"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("run", sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True))
    op.add_column(
        "run",
        sa.Column("interrupt_payload", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_run_tenant_app_user_started",
        "run",
        ["tenant_id", "workflow_id", "user_id", "started_at"],
    )
    # 部分索引：待审批列表只扫中断行
    op.create_index(
        "ix_run_tenant_app_interrupted",
        "run",
        ["tenant_id", "workflow_id"],
        postgresql_where=sa.text("execute_status = 'interrupted'"),
    )


def downgrade() -> None:
    op.drop_index("ix_run_tenant_app_interrupted", table_name="run")
    op.drop_index("ix_run_tenant_app_user_started", table_name="run")
    op.drop_column("run", "interrupt_payload")
    op.drop_column("run", "user_id")
