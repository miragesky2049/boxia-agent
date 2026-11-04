"""幂等请求去重仓储：entitlement_request_log 裸 SQL（P3-8）。

只依赖 SQLAlchemy Core / text，不 import application 层（DDD 依赖方向：infra → domain）。
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid
from internal.infrastructure.repository.apps.entitlement_repository import cast_cursor


class EntitlementRequestLogRepository:
    """结构性满足 EntitlementRequestLogRepositoryProtocol 的 PostgreSQL 实现。"""

    def __init__(self, session: Session):
        self._session = session

    def try_begin(self, request_id: str, tenant_id: UUID, action: str, payload: dict) -> bool:
        result = cast_cursor(
            self._session.execute(
                text(
                    "INSERT INTO entitlement_request_log "
                    "(id, request_id, tenant_id, action, status, version, payload) "
                    "VALUES (:id, :rid, :tid, :action, 'processing', 1, CAST(:payload AS JSONB)) "
                    "ON CONFLICT (request_id) DO NOTHING"
                ),
                {
                    "id": new_uuid(),
                    "rid": request_id,
                    "tid": tenant_id,
                    "action": action,
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
        )
        return int(result.rowcount) == 1

    def get(self, request_id: str) -> dict[str, Any] | None:
        row = self._session.execute(
            text(
                "SELECT request_id, status, version, result FROM entitlement_request_log "
                "WHERE request_id = :rid"
            ),
            {"rid": request_id},
        ).first()
        return dict(row._mapping) if row else None

    def retry_begin(self, request_id: str) -> None:
        self._session.execute(
            text(
                "UPDATE entitlement_request_log "
                "SET status = 'processing', version = version + 1, result = NULL, "
                "    updated_at = NOW() "
                "WHERE request_id = :rid AND status = 'failed'"
            ),
            {"rid": request_id},
        )

    def mark_completed(self, request_id: str, result: dict) -> None:
        self._session.execute(
            text(
                "UPDATE entitlement_request_log "
                "SET status = 'completed', result = CAST(:result AS JSONB), "
                "    completed_at = NOW(), updated_at = NOW() "
                "WHERE request_id = :rid"
            ),
            {"rid": request_id, "result": json.dumps(result, ensure_ascii=False, default=str)},
        )

    def mark_failed(self, request_id: str) -> None:
        self._session.execute(
            text(
                "UPDATE entitlement_request_log "
                "SET status = 'failed', updated_at = NOW() WHERE request_id = :rid"
            ),
            {"rid": request_id},
        )
