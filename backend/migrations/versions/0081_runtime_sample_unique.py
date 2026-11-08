"""0081 eval_result 线上采样幂等唯一索引（M4 PRD F19.3，T-d8 批末 review P2-1）。

背景：采样幂等目前仅靠 has_runtime_sample SELECT 探测，双 worker 并行消费同一 run
（broker 重投 / acks_late 可见性超时双跑）存在探测双双放行的竞态窗口，与"绝不重复
计费"硬契约冲突。部分唯一索引把幂等下沉到 DB：同 run 第二条 runtime_sample 行撞
约束、事务整体回滚（judge 计量与结果行同事务，天然无半写入）。
仅约束采样行：eval_run 批结果一 run 多评估器多行、runtime_gate 一 run 可多终判，不受影响。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0081_runtime_sample_unique"
down_revision: str | None = "0080_run_is_eval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 历史脏数据防御：约束上线前同 run 重复行先收敛为最早一条（uuid7 时间有序）
    op.execute(
        "DELETE FROM eval_result er WHERE er.source = 'runtime_sample' AND EXISTS ("
        "SELECT 1 FROM eval_result e2 WHERE e2.run_id = er.run_id "
        "AND e2.source = 'runtime_sample' AND e2.id < er.id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_eval_result_runtime_sample_run "
        "ON eval_result (run_id) WHERE source = 'runtime_sample'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_eval_result_runtime_sample_run")
