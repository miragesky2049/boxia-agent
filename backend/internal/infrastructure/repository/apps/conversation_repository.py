"""会话仓储：conversation 表读写。"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
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
                "created_at, updated_at, "
                # M4 PRD F15.2：摘要与水位线（ChatService 组装短期记忆时消费）
                "summary, summary_through_message_id, summary_updated_at, "
                # M4 PRD F14.9：接管路由态（统一入口分派与会话列表消费）
                "active_application_id, handoff_chain "
                "FROM conversation WHERE id = :id"
            ),
            {"id": conversation_id},
        ).first()
        return dict(row._mapping) if row else None

    def update_handoff_state(
        self,
        conversation_id: UUID,
        *,
        active_application_id: UUID | None,
        handoff_chain: list[str],
    ) -> None:
        """写接管路由态（M4 PRD F14.9）：active_application_id=None 即归位主助手。

        调用方约束（R21）：接管切换只允许发生在 run 成功提交后；本方法只做存取，
        链深/去环判定在 domain/agent/handoff，仓储不重复校验。
        """
        self._session.execute(
            text(
                "UPDATE conversation SET active_application_id = :active, "
                "handoff_chain = CAST(:chain AS JSONB), updated_at = now() WHERE id = :id"
            ),
            {
                "id": conversation_id,
                "active": active_application_id,
                "chain": json.dumps([str(item) for item in handoff_chain or []]),
            },
        )

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
                # M4 PRD F14.10：发言权指针（会话列表徽标 additive 透出）
                "created_at, updated_at, active_application_id "
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
            text("UPDATE conversation SET title = :title, updated_at = now() WHERE id = :id"),
            {"id": conversation_id, "title": title},
        )

    def touch(self, conversation_id: UUID) -> None:
        """刷新会话更新时间：每轮消息落库后调用，保证列表按最近活跃排序。"""
        self._session.execute(
            text("UPDATE conversation SET updated_at = now() WHERE id = :id"),
            {"id": conversation_id},
        )

    def update_summary_if_marker(
        self,
        conversation_id: UUID,
        *,
        old_marker: UUID | None,
        summary: str,
        new_marker: UUID | None,
    ) -> bool:
        """摘要回写乐观并发（M4 PRD F15.4）：水位线未被并发轮次前移时才生效。

        IS NOT DISTINCT FROM 做空值安全比较——首次总结旧水位为 None 也能命中；
        返回 False 表示本轮放弃写入（不报错），旧摘要自然由下一轮重算收口。
        """
        result = self._session.execute(
            text(
                "UPDATE conversation SET summary = :summary, "
                "summary_through_message_id = :new_marker, summary_updated_at = now() "
                "WHERE id = :id "
                "AND summary_through_message_id IS NOT DISTINCT FROM :old_marker"
            ),
            {
                "id": conversation_id,
                "summary": summary,
                "new_marker": new_marker,
                "old_marker": old_marker,
            },
        )
        return cast("CursorResult[Any]", result).rowcount > 0

    def clear_summary(self, conversation_id: UUID) -> None:
        """清空摘要正文与水位线（M4 PRD F15.7：清空上下文时联动失效，防残留摘要继续注入）。"""
        self._session.execute(
            text(
                "UPDATE conversation SET summary = NULL, "
                "summary_through_message_id = NULL, summary_updated_at = NULL "
                "WHERE id = :id"
            ),
            {"id": conversation_id},
        )

    def delete_conversation(self, conversation_id: UUID) -> None:
        """删除会话；message 表通过 ON DELETE CASCADE 级联清理。"""
        self._session.execute(
            text("DELETE FROM conversation WHERE id = :id"),
            {"id": conversation_id},
        )
