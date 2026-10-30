"""运行实例仓储：run + run_node_execution。

字段命名对齐 coze 前端对象：
- run.workflow_id（原 application_id）
- run.execute_status（原 status）
- run.error_message（原 error）
- run.thread_id（原 langgraph_thread_id）
- run_node_execution.execute_id（原 run_id）
- run_node_execution.error_message（原 error）
- run_node_execution.usage（原 token_usage）
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class RunRepository:
    """运行实例仓储，用原生 SQL 操作。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== run ==========
    def insert_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        workflow_id: UUID,
        graph_snapshot: dict[str, Any],
        input_data: dict[str, Any],
        thread_id: str,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO run (id, tenant_id, workflow_id, graph_snapshot, input, "
                "thread_id, execute_status) VALUES "
                "(:id, :tid, :wid, CAST(:snapshot AS JSONB), CAST(:input AS JSONB), :thread, 'running')"
            ),
            {
                "id": run_id,
                "tid": tenant_id,
                "wid": workflow_id,
                "snapshot": json.dumps(graph_snapshot),
                "input": json.dumps(input_data),
                "thread": thread_id,
            },
        )

    def update_run_status(
        self,
        run_id: UUID,
        *,
        execute_status: str,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        self._session.execute(
            text(
                "UPDATE run SET execute_status = :status, output = CAST(:output AS JSONB), "
                "error_message = :error, finished_at = now() WHERE id = :id"
            ),
            {
                "id": run_id,
                "status": execute_status,
                "output": json.dumps(output) if output is not None else None,
                "error": error_message,
            },
        )

    def get_run(self, run_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, tenant_id, workflow_id, input, output, execute_status, error_message, "
                "thread_id, started_at, finished_at FROM run WHERE id = :id"
            ),
            {"id": run_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_running_by_thread(
        self,
        tenant_id: UUID,
        workflow_id: UUID,
        thread_id: str,
    ) -> dict | None:
        """按 thread_id 查找该租户该应用下最近一条未结束的 run（用于 resume 复用 run_id）。"""
        row = self._session.execute(
            text(
                "SELECT id, execute_status FROM run "
                "WHERE tenant_id = :tid AND workflow_id = :wid "
                "AND thread_id = :thread "
                "AND execute_status IN ('running', 'interrupted') "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "wid": workflow_id, "thread": thread_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_runs(
        self,
        tenant_id: UUID,
        *,
        workflow_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = (
            "SELECT id, workflow_id, thread_id, execute_status, input, output, error_message, started_at, finished_at "
            "FROM run WHERE tenant_id = :tid"
        )
        params: dict[str, Any] = {"tid": tenant_id}
        if workflow_id is not None:
            sql += " AND workflow_id = :wid"
            params["wid"] = workflow_id
        sql += " ORDER BY started_at DESC LIMIT :limit"
        params["limit"] = limit
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    # ========== run_node_execution ==========
    def insert_node_execution(
        self,
        *,
        execute_id: UUID,
        node_id: str,
        node_type: str,
        input_data: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO run_node_execution "
                "(id, execute_id, node_id, node_type, input, output, error_message, "
                "started_at, finished_at, duration_ms, usage) VALUES "
                "(:id, :rid, :nid, :ntype, CAST(:input AS JSONB), CAST(:output AS JSONB), "
                ":error, :started, :finished, :duration, CAST(:tokens AS JSONB))"
            ),
            {
                "id": new_uuid(),
                "rid": execute_id,
                "nid": node_id,
                "ntype": node_type,
                "input": json.dumps(input_data) if input_data is not None else None,
                "output": json.dumps(output) if output is not None else None,
                "error": error_message,
                "started": started_at or datetime.utcnow(),
                "finished": finished_at,
                "duration": duration_ms,
                "tokens": json.dumps(usage) if usage is not None else None,
            },
        )

    def list_node_executions(self, execute_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, node_id, node_type, input, output, error_message, "
                "started_at, finished_at, duration_ms, usage "
                "FROM run_node_execution WHERE execute_id = :rid ORDER BY started_at"
            ),
            {"rid": execute_id},
        ).all()
        return [dict(r._mapping) for r in rows]
