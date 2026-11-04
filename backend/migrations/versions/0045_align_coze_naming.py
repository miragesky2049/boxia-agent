"""DB 字段对齐 coze 前端对象命名。

对齐映射：
- application_graph.graph            -> schema_json
- application_graph_version.graph     -> schema_json
- run.application_id                  -> workflow_id
- run.status                         -> execute_status
- run.error                          -> error_message
- run.langgraph_thread_id            -> thread_id
- run_node_execution.run_id          -> execute_id
- run_node_execution.error           -> error_message
- run_node_execution.token_usage     -> usage

Revision ID: 0045_align_coze_naming
Revises: 0044_conversation_message
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_align_coze_naming"
down_revision: str | None = "0044_conversation_message"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. application_graph / application_graph_version: graph -> schema_json
    op.alter_column("application_graph", "graph", new_column_name="schema_json")
    op.alter_column("application_graph_version", "graph", new_column_name="schema_json")

    # 2. run 表字段对齐
    op.alter_column("run", "application_id", new_column_name="workflow_id")
    op.alter_column("run", "status", new_column_name="execute_status")
    op.alter_column("run", "error", new_column_name="error_message")
    op.alter_column("run", "langgraph_thread_id", new_column_name="thread_id")

    # 3. run_node_execution 表字段对齐
    op.alter_column("run_node_execution", "run_id", new_column_name="execute_id")
    op.alter_column("run_node_execution", "error", new_column_name="error_message")
    op.alter_column("run_node_execution", "token_usage", new_column_name="usage")

    # 4. 重建受影响的索引（列名变了）
    op.drop_index("ix_run_app", table_name="run")
    op.create_index("ix_run_app", "run", ["workflow_id", sa.text("started_at")])

    op.drop_index("ix_node_exec_run", table_name="run_node_execution")
    op.create_index("ix_node_exec_run", "run_node_execution", ["execute_id", "node_id"])

    # 5. 重建 check 约束（列名变了）
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "execute_status IN ('running', 'success', 'error', 'interrupted')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "status IN ('running', 'success', 'error', 'interrupted')",
    )

    op.drop_index("ix_node_exec_run", table_name="run_node_execution")
    op.create_index("ix_node_exec_run", "run_node_execution", ["run_id", "node_id"])

    op.drop_index("ix_run_app", table_name="run")
    op.create_index("ix_run_app", "run", ["application_id", sa.text("started_at")])

    op.alter_column("run_node_execution", "usage", new_column_name="token_usage")
    op.alter_column("run_node_execution", "error_message", new_column_name="error")
    op.alter_column("run_node_execution", "execute_id", new_column_name="run_id")

    op.alter_column("run", "thread_id", new_column_name="langgraph_thread_id")
    op.alter_column("run", "error_message", new_column_name="error")
    op.alter_column("run", "execute_status", new_column_name="status")
    op.alter_column("run", "workflow_id", new_column_name="application_id")

    op.alter_column("application_graph_version", "schema_json", new_column_name="graph")
    op.alter_column("application_graph", "schema_json", new_column_name="graph")
