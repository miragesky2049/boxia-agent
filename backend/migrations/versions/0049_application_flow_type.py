"""0049 application 加 flow_type：区分工作流与对话流。

Revision ID: 0049_application_flow_type
Revises: 0048_document_permissions
Create Date: 2026-11-02

设计要点：
- flow_type 是应用级属性，不参与 graph 版本快照
- 存量应用统一默认 workflow，行为不变
- chatflow 才有 USER_INPUT / CONVERSATION_NAME 系统输入、输出节点、问答节点
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_application_flow_type"
down_revision: str | None = "0048_document_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application",
        sa.Column(
            "flow_type",
            sa.String(length=20),
            nullable=False,
            server_default="workflow",
            comment="workflow（工作流） / chatflow（对话流）",
        ),
    )
    op.create_check_constraint(
        "ck_application_flow_type",
        "application",
        "flow_type IN ('workflow', 'chatflow')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_application_flow_type", "application", type_="check")
    op.drop_column("application", "flow_type")
