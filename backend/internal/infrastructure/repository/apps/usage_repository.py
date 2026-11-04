"""租户用量账仓储：tenant_usage_ledger。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class UsageRepository:
    """租户用量账仓储，用原生 SQL 操作。"""

    def __init__(self, session: Session):
        self._session = session

    def record_usage(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        run_id: UUID,
        node_id: str,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        user_id: UUID | None = None,
    ) -> None:
        self._session.execute(
            text(
                "INSERT INTO tenant_usage_ledger "
                "(id, tenant_id, application_id, run_id, node_id, model_id, "
                "prompt_tokens, completion_tokens, total_tokens, user_id) VALUES "
                "(:id, :tid, :aid, :rid, :nid, :mid, :pt, :ct, :tt, :uid)"
            ),
            {
                "id": new_uuid(),
                "tid": tenant_id,
                "aid": application_id,
                "rid": run_id,
                "nid": node_id,
                "mid": model_id,
                "pt": prompt_tokens,
                "ct": completion_tokens,
                "tt": total_tokens,
                "uid": user_id,
            },
        )

    def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        application_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = (
            "SELECT id, application_id, run_id, node_id, model_id, "
            "prompt_tokens, completion_tokens, total_tokens, created_at "
            "FROM tenant_usage_ledger WHERE tenant_id = :tid"
        )
        params: dict[str, Any] = {"tid": tenant_id}
        if application_id is not None:
            sql += " AND application_id = :aid"
            params["aid"] = application_id
        sql += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = limit
        rows = self._session.execute(text(sql), params).all()
        return [dict(r._mapping) for r in rows]
