"""0075 run 表：parent_run_id（工作流即工具子 run 归因）+ execute_status 增加 cancelled。

背景（docs/agent-app-prd.md F7.2 / R6）：
- F7.2：智能体把已发布 workflow 作为工具执行时，子 run 独立落 run 表并以
  parent_run_id 关联父 run，供运行日志页展开子 run 明细；
- R6：客户端断连导致画布任务取消时，run 标记为 cancelled（区别于 success/error），
  因此放开 ck_run_status 取值。
存量行不受影响：parent_run_id 可空、cancelled 为新增取值。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075_run_parent_and_cancelled"
down_revision: str | None = "0074_agent_flow_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "run",
        sa.Column(
            "parent_run_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("run.id", ondelete="CASCADE"),
            nullable=True,
            comment="工作流即工具：触发本 run 的父 run（0074 PRD F7.2）",
        ),
    )
    op.create_index("ix_run_parent_run_id", "run", ["parent_run_id"])

    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "execute_status IN ('running', 'success', 'error', 'interrupted', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "execute_status IN ('running', 'success', 'error', 'interrupted')",
    )
    op.drop_index("ix_run_parent_run_id", table_name="run")
    op.drop_column("run", "parent_run_id")
