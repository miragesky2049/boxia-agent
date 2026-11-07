"""0074 application.flow_type 增加 agent：智能体应用类型。

背景（docs/agent-app-prd.md F1）：workflow / chatflow 均为固定流程定义，
"智能体"此前只存在于画布 agent_loop 节点（type_code=100）与 runtime_mode 维度，
没有应用级类型。本迁移放开 CHECK 约束，新增 'agent' 取值：
- agent 型应用的运行时载体 = start→agent_loop→end 标准画布（配置面表单读写其节点 config）；
- 存量应用不受影响，默认口径仍为 workflow。
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0074_agent_flow_type"
down_revision: str | None = "0073_role_access_removal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_application_flow_type", "application", type_="check")
    op.create_check_constraint(
        "ck_application_flow_type",
        "application",
        "flow_type IN ('workflow', 'chatflow', 'agent')",
    )


def downgrade() -> None:
    # 回滚前先收敛存量 agent 行，否则新 CHECK 建立即失败
    op.execute("UPDATE application SET flow_type = 'chatflow' WHERE flow_type = 'agent'")
    op.drop_constraint("ck_application_flow_type", "application", type_="check")
    op.create_check_constraint(
        "ck_application_flow_type",
        "application",
        "flow_type IN ('workflow', 'chatflow')",
    )
