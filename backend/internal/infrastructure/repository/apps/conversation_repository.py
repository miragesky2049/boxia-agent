"""会话仓储：conversation 表读写。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class ConversationRepository:
    """会话仓储，原生 SQL 操作。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_conversation(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID,
        title: str = "",
    ) -> UUID:
        cid = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO conversation (id, tenant_id, user_id, application_id, title) "
                "VALUES (:id, :tid, :uid, :aid, :title)"
            ),
            {
                "id": cid,
                "tid": tenant_id,
                "uid": user_id,
                "aid": application_id,
                "title": title,
            },
        )
        return cid

    def get_conversation(self, conversation_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, tenant_id, user_id, application_id, title, created_at, updated_at "
                "FROM conversation WHERE id = :id"
            ),
            {"id": conversation_id},
        ).first()
        return dict(row._mapping) if row else None

    def update_title(self, conversation_id: UUID, title: str) -> None:
        self._session.execute(
            text(
                "UPDATE conversation SET title = :title, updated_at = now() WHERE id = :id"
            ),
            {"id": conversation_id, "title": title},
        )
