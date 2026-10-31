"""会话仓储：conversation 表读写。"""

from __future__ import annotations

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

    def list_conversations_by_user(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """按 updated_at 倒序列出某用户的会话列表。"""
        params: dict[str, Any] = {
            "tid": tenant_id,
            "uid": user_id,
            "limit": limit,
            "offset": offset,
        }
        app_filter = ""
        if application_id is not None:
            app_filter = "AND application_id = :aid"
            params["aid"] = application_id
        rows = self._session.execute(
            text(
                "SELECT id, tenant_id, user_id, application_id, title, created_at, updated_at "
                "FROM conversation "
                "WHERE tenant_id = :tid AND user_id = :uid "
                f"{app_filter} "
                "ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        return [dict(r._mapping) for r in rows]

    def update_title(self, conversation_id: UUID, title: str) -> None:
        self._session.execute(
            text(
                "UPDATE conversation SET title = :title, updated_at = now() WHERE id = :id"
            ),
            {"id": conversation_id, "title": title},
        )

    def delete_conversation(self, conversation_id: UUID) -> None:
        """删除会话；message 表通过 ON DELETE CASCADE 级联清理。"""
        self._session.execute(
            text("DELETE FROM conversation WHERE id = :id"),
            {"id": conversation_id},
        )
