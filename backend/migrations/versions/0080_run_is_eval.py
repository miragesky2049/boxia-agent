"""0080 run 表 is_eval 标记列（M4 PRD F18.3）。

背景（docs/agent-m4-prd.md F18.3）：评测批跑对每条 case 直调 GraphRuntime 会产生
真实 run 行（is_eval=true 归因，报告"跳转 run 详情"依赖它）；运行日志列表默认
过滤 is_eval=false，避免评测流量污染人工排查视图。get_run 不过滤（详情可见）。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0080_run_is_eval"
down_revision: str | None = "0079_eval_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE run ADD COLUMN is_eval BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE run DROP COLUMN IF EXISTS is_eval")
