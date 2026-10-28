"""v4 运行实例仓储：run + run_node_execution。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class V4RunRepository:
    """运行实例仓储，用原生 SQL 操作。"""

    def __init__(self, session: Session):
        self._session = session

    # ========== run ==========
    def insert_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        application_id: UUID,
        graph_snapshot: dict[str, Any],
        input_data: dict[str, Any],
        langgraph_thread_id: str,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO run (id, tenant_id, application_id, graph_snapshot, input, "
                "langgraph_thread_id, status) VALUES "
                "(:id, :tid, :aid, CAST(:snapshot AS JSONB), CAST(:input AS JSONB), :thread, 'running')"
            ),
            {
                "id": run_id,
                "tid": tenant_id,
                "aid": application_id,
                "snapshot": json.dumps(graph_snapshot),
                "input": json.dumps(input_data),
                "thread": langgraph_thread_id,
            },
        )

    def update_run_status(
        self,
        run_id: UUID,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self._session.execute(
            text(
                "UPDATE run SET status = :status, output = CAST(:output AS JSONB), "
                "error = :error, finished_at = now() WHERE id = :id"
            ),
            {
                "id": run_id,
                "status": status,
                "output": json.dumps(output) if output is not None else None,
                "error": error,
            },
        )

    def get_run(self, run_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, tenant_id, application_id, input, output, status, error, "
                "langgraph_thread_id, started_at, finished_at FROM run WHERE id = :id"
            ),
            {"id": run_id},
        ).first()
        return dict(row._mapping) if row else None

    def get_running_by_thread(
        self,
        tenant_id: UUID,
        application_id: UUID,
        langgraph_thread_id: str,
    ) -> dict | None:
        """按 thread_id 查找该租户该应用下最近一条未结束的 run（用于 resume 复用 run_id）。"""
        row = self._session.execute(
            text(
                "SELECT id, status FROM run "
                "WHERE tenant_id = :tid AND application_id = :aid "
                "AND langgraph_thread_id = :thread "
                "AND status IN ('running', 'interrupted') "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"tid": tenant_id, "aid": application_id, "thread": langgraph_thread_id},
        ).first()
        return dict(row._mapping) if row else None

    def list_runs(
        self,
        tenant_id: UUID,
        *,
        application_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = (
            "SELECT id, application_id, status, input, output, error, started_at, finished_at "
            "FROM run WHERE tenant_id = :tid"
        )
        params: dict[str, Any] = {"tid": tenant_id}
        if application_id is not None:
            sql += " AND application_id = :aid"
            params["aid"] = application_id
        sql += " ORDER BY started_at DESC LIMIT :limit"
        params["limit"] = limit
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]

    # ========== run_node_execution ==========
    def insert_node_execution(
        self,
        *,
        run_id: UUID,
        node_id: str,
        node_type: str,
        input_data: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO run_node_execution "
                "(id, run_id, node_id, node_type, input, output, error, "
                "started_at, finished_at, duration_ms, token_usage) VALUES "
                "(:id, :rid, :nid, :ntype, CAST(:input AS JSONB), CAST(:output AS JSONB), "
                ":error, :started, :finished, :duration, CAST(:tokens AS JSONB))"
            ),
            {
                "id": new_uuid(),
                "rid": run_id,
                "nid": node_id,
                "ntype": node_type,
                "input": json.dumps(input_data) if input_data is not None else None,
                "output": json.dumps(output) if output is not None else None,
                "error": error,
                "started": started_at or datetime.utcnow(),
                "finished": finished_at,
                "duration": duration_ms,
                "tokens": json.dumps(token_usage) if token_usage is not None else None,
            },
        )

    def list_node_executions(self, run_id: UUID) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, node_id, node_type, input, output, error, "
                "started_at, finished_at, duration_ms, token_usage "
                "FROM run_node_execution WHERE run_id = :rid ORDER BY started_at"
            ),
            {"rid": run_id},
        ).all()
        return [dict(r._mapping) for r in rows]
