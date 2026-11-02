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
        channel: str = "api",
    ) -> UUID:
        cid = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO conversation (id, tenant_id, user_id, application_id, title, channel) "
                "VALUES (:id, :tid, :uid, :aid, :title, :channel)"
            ),
            {
                "id": cid,
                "tid": tenant_id,
                "uid": user_id,
                "aid": application_id,
                "title": title,
                "channel": channel,
            },
        )
        return cid

    def get_conversation(self, conversation_id: UUID) -> dict | None:
        row = self._session.execute(
            text(
                "SELECT id, tenant_id, user_id, application_id, title, channel, "
                "created_at, updated_at "
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
        channel: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """按 updated_at 倒序列出某用户的会话列表；channel 为空时不过滤。"""
        params: dict[str, Any] = {
            "tid": tenant_id,
            "uid": user_id,
            "limit": limit,
            "offset": offset,
        }
        filters = ""
        if application_id is not None:
            filters += " AND application_id = :aid"
            params["aid"] = application_id
        if channel is not None:
            filters += " AND channel = :channel"
            params["channel"] = channel
        rows = self._session.execute(
            text(
                "SELECT id, tenant_id, user_id, application_id, title, channel, "
                "created_at, updated_at "
                "FROM conversation "
                "WHERE tenant_id = :tid AND user_id = :uid "
                f"{filters} "
                "ORDER BY updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            params,
        ).all()
        return [dict(r._mapping) for r in rows]

    def list_conversations_by_application(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """管理端视角：列出某应用下全部会话（按 updated_at 倒序），附带所属用户信息。

        会话归属有两种用户：用户端会话（channel=api）对应 users，
        画布试运行会话（channel=debug）对应 admin_users，因此两张表都要关联。
        """
        rows = self._session.execute(
            text(
                "SELECT c.id, c.tenant_id, c.user_id, c.application_id, c.title, c.channel, "
                "c.created_at, c.updated_at, "
                "COALESCE(u.username, a.username) AS username, "
                "COALESCE(u.display_name, a.display_name) AS display_name "
                "FROM conversation c "
                "LEFT JOIN users u ON u.id = c.user_id "
                "LEFT JOIN admin_users a ON a.id = c.user_id "
                "WHERE c.tenant_id = :tid AND c.application_id = :aid "
                "ORDER BY c.updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"tid": tenant_id, "aid": application_id, "limit": limit, "offset": offset},
        ).all()
        return [dict(r._mapping) for r in rows]

    def update_title(self, conversation_id: UUID, title: str) -> None:
        self._session.execute(
            text(
                "UPDATE conversation SET title = :title, updated_at = now() WHERE id = :id"
            ),
            {"id": conversation_id, "title": title},
        )

    def touch(self, conversation_id: UUID) -> None:
        """刷新会话更新时间：每轮消息落库后调用，保证列表按最近活跃排序。"""
        self._session.execute(
            text("UPDATE conversation SET updated_at = now() WHERE id = :id"),
            {"id": conversation_id},
        )

    def delete_conversation(self, conversation_id: UUID) -> None:
        """删除会话；message 表通过 ON DELETE CASCADE 级联清理。"""
        self._session.execute(
            text("DELETE FROM conversation WHERE id = :id"),
            {"id": conversation_id},
        )
