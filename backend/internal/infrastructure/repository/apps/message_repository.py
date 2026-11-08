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
                "SELECT id, conversation_id, application_id, role, content, tool_calls, "
                "tool_call_id, tool_name, run_id, metadata, created_at "
                "FROM message WHERE conversation_id = :cid "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"cid": conversation_id, "limit": limit},
        ).all()
        items = [dict(r._mapping) for r in rows]
        items.reverse()
        return items

    def list_messages_by_run(self, run_id: UUID) -> list[dict]:
        """按 run 取本轮 user/assistant 文本行（M4 PRD F16.3 抽取输入）。

        排序用 id ASC：uuid7 时间有序，同事务落库的 created_at 相等不可辨序。
        """
        rows = self._session.execute(
            text(
                "SELECT id, conversation_id, role, content, created_at FROM message "
                "WHERE run_id = :rid AND role IN ('user', 'assistant') ORDER BY id ASC"
            ),
            {"rid": run_id},
        ).all()
        return [dict(r._mapping) for r in rows]

    def get_message(self, message_id: UUID) -> dict | None:
        """按消息 ID 查行（用于跨租户删除前的归属校验）。"""
        row = self._session.execute(
            text(
                "SELECT id, conversation_id, tenant_id, user_id, application_id "
                "FROM message WHERE id = :id"
            ),
            {"id": message_id},
        ).first()
        return dict(row._mapping) if row else None

    def delete_message(self, message_id: UUID) -> None:
        self._session.execute(
            text("DELETE FROM message WHERE id = :id"),
            {"id": message_id},
        )

    def clear_messages(self, conversation_id: UUID) -> None:
        self._session.execute(
            text("DELETE FROM message WHERE conversation_id = :cid"),
            {"cid": conversation_id},
        )
