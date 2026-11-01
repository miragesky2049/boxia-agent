"""webhook 通知仓储：event_webhook。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class WebhookRepository:
    """租户 webhook 订阅仓储。"""

    def __init__(self, session: Session):
        self._session = session

    def list_for_event(
        self,
        tenant_id: UUID,
        event_type: str,
        application_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """查询某租户某事件类型的启用 webhook（含应用级 + 租户级 application_id IS NULL）。"""
        sql = text(
            "SELECT id, tenant_id, application_id, event_type, url "
            "FROM event_webhook "
            "WHERE tenant_id = :tid AND event_type = :et AND is_enabled = true "
            "AND (application_id IS NULL OR application_id = :aid)"
        )
        rows = self._session.execute(
            sql,
            {"tid": tenant_id, "et": event_type, "aid": application_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def create(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        url: str,
        application_id: UUID | None = None,
    ) -> UUID:
        webhook_id = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO event_webhook (id, tenant_id, application_id, event_type, url) "
                "VALUES (:id, :tid, :aid, :et, :url)"
            ),
            {
                "id": webhook_id,
                "tid": tenant_id,
                "aid": application_id,
                "et": event_type,
                "url": url,
            },
        )
        return webhook_id

    def list_by_tenant(self, tenant_id: UUID) -> list[dict[str, Any]]:
        rows = self._session.execute(
            text(
                "SELECT id, tenant_id, application_id, event_type, url, is_enabled, created_at "
                "FROM event_webhook WHERE tenant_id = :tid ORDER BY created_at DESC"
            ),
            {"tid": tenant_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def delete(self, webhook_id: UUID, tenant_id: UUID) -> None:
        self._session.execute(
            text("DELETE FROM event_webhook WHERE id = :id AND tenant_id = :tid"),
            {"id": webhook_id, "tid": tenant_id},
        )
