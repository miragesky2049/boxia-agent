"""消息仓储：message 表读写。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from internal.infrastructure.id.uuid7 import new_uuid


class MessageRepository:
    """消息仓储，原生 SQL 操作。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append_message(
        self,
        *,
        conversation_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        run_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        mid = new_uuid()
        self._session.execute(
            text(
                "INSERT INTO message "
                "(id, conversation_id, tenant_id, user_id, application_id, role, content, "
                " tool_calls, tool_call_id, tool_name, run_id, metadata) VALUES "
                "(:id, :cid, :tid, :uid, :aid, :role, :content, "
                " CAST(:tool_calls AS JSONB), :tool_call_id, :tool_name, :run_id, "
                " CAST(:metadata AS JSONB))"
            ),
            {
                "id": mid,
                "cid": conversation_id,
                "tid": tenant_id,
                "uid": user_id,
                "aid": application_id,
                "role": role,
                "content": content,
                "tool_calls": json.dumps(tool_calls) if tool_calls else None,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "run_id": run_id,
                "metadata": json.dumps(metadata or {}),
            },
        )
        return mid

    def list_messages_by_conversation(
        self,
        conversation_id: UUID,
        *,
        limit: int = 50,
    ) -> list[dict]:
        rows = self._session.execute(
            text(
                "SELECT id, conversation_id, role, content, tool_calls, tool_call_id, "
                "tool_name, run_id, metadata, created_at "
                "FROM message WHERE conversation_id = :cid "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"cid": conversation_id, "limit": limit},
        ).all()
        items = [dict(r._mapping) for r in rows]
        items.reverse()
        return items
