"""把 sync SQLAlchemy 会话/消息仓储包装成 async ABC 实现，供 workflow 节点注入。

节点 handler 依赖 `internal.domain.agent.repository.ConversationRepository / MessageRepository`
这两个 async ABC；实际 DB 仓储（`ConversationRepository` / `MessageRepository`）是 sync 的。
这里做一层薄适配：
- 调用方在请求级把 tenant_id / user_id / application_id 绑定进 adapter
- create / append 时优先用领域对象上的字段，缺省时用绑定值兜底
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from internal.domain.agent.model import Conversation, Message, ToolCall
from internal.domain.agent.repository import (
    ConversationRepository as ConversationRepositoryABC,
    MessageRepository as MessageRepositoryABC,
)
from internal.infrastructure.repository.apps.conversation_repository import (
    ConversationRepository as SyncConversationRepository,
)
from internal.infrastructure.repository.apps.message_repository import (
    MessageRepository as SyncMessageRepository,
)


def _row_to_conversation(row: dict) -> Conversation:
    """DB row -> 领域 Conversation。"""
    return Conversation(
        conversation_id=row["id"],
        app_id=row.get("application_id"),
        tenant_id=row.get("tenant_id"),
        user_id=row.get("user_id"),
        title=row.get("title") or "",
        created_at=row.get("created_at") or datetime.now(timezone.utc),
        updated_at=row.get("updated_at") or datetime.now(timezone.utc),
        metadata={},
    )


def _row_to_message(row: dict) -> Message:
    """DB row -> 领域 Message。"""
    tool_calls_raw = row.get("tool_calls")
    if isinstance(tool_calls_raw, str):
        try:
            tool_calls_raw = json.loads(tool_calls_raw or "[]")
        except json.JSONDecodeError:
            tool_calls_raw = []
    tool_calls = [
        ToolCall(
            call_id=tc.get("call_id") or tc.get("id") or "",
            name=tc.get("name") or "",
            arguments=tc.get("arguments") or {},
        )
        for tc in (tool_calls_raw or [])
    ]
    return Message(
        message_id=row["id"],
        conversation_id=row["conversation_id"],
        role=row.get("role") or "user",
        content=row.get("content") or "",
        tool_calls=tool_calls,
        tool_call_id=row.get("tool_call_id"),
        name=row.get("tool_name"),
        created_at=row.get("created_at") or datetime.now(timezone.utc),
        metadata=row.get("metadata") or {},
    )


class AsyncConversationRepository(ConversationRepositoryABC):
    """把 sync ConversationRepository 适配成 async ABC。"""

    def __init__(
        self,
        sync_repo: SyncConversationRepository,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        application_id: UUID,
        enforce_application: bool = True,
        channel: str = "api",
    ) -> None:
        self._repo = sync_repo
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._application_id = application_id
        # 画布 debug 试运行没有真实应用 ID，允许按租户+用户跨应用读写会话
        self._enforce_application = enforce_application
        # debug 会话不进用户端会话列表
        self._channel = channel

    def _assert_in_scope(self, row: dict | None) -> dict | None:
        """校验会话归属：不在绑定作用域内返回 None。"""
        if not row:
            return None
        if row.get("tenant_id") != self._tenant_id:
            return None
        if self._user_id is not None and row.get("user_id") not in (None, self._user_id):
            return None
        if self._enforce_application and row.get("application_id") not in (None, self._application_id):
            return None
        return row

    async def create(self, conversation: Conversation) -> Conversation:
        tenant_id = conversation.tenant_id or self._tenant_id
        user_id = conversation.user_id or self._user_id
        app_id = conversation.app_id or self._application_id
        if user_id is None:
            raise ValueError("创建会话缺少 user_id")
        cid = self._repo.insert_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            application_id=app_id,
            title=conversation.title,
            channel=self._channel,
        )
        saved = self._repo.get_conversation(cid)
        return _row_to_conversation(saved) if saved else Conversation(
            conversation_id=cid,
            app_id=app_id,
            tenant_id=tenant_id,
            user_id=user_id,
            title=conversation.title,
        )

    async def get(self, conversation_id: UUID) -> Conversation | None:
        row = self._assert_in_scope(self._repo.get_conversation(conversation_id))
        return _row_to_conversation(row) if row else None

    async def list_by_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        app_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Conversation]:
        rows = self._repo.list_conversations_by_user(
            tenant_id=tenant_id,
            user_id=user_id,
            application_id=app_id,
            limit=limit,
            offset=offset,
        )
        return [_row_to_conversation(r) for r in rows]

    async def delete(self, conversation_id: UUID) -> None:
        row = self._assert_in_scope(self._repo.get_conversation(conversation_id))
        if row is None:
            return
        self._repo.delete_conversation(conversation_id)

    async def update_title(self, conversation_id: UUID, title: str) -> None:
        row = self._assert_in_scope(self._repo.get_conversation(conversation_id))
        if row is None:
            return
        self._repo.update_title(conversation_id, title)


class AsyncMessageRepository(MessageRepositoryABC):
    """把 sync MessageRepository 适配成 async ABC。"""

    def __init__(
        self,
        sync_repo: SyncMessageRepository,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        application_id: UUID,
        run_id: UUID | None = None,
        enforce_application: bool = True,
    ) -> None:
        self._repo = sync_repo
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._application_id = application_id
        self._run_id = run_id
        self._enforce_application = enforce_application

    def _assert_conversation_in_scope(self, conversation_id: UUID) -> dict | None:
        """校验会话归属：不在绑定作用域内返回 None。"""
        row = self._repo.get_conversation(conversation_id)
        if not row:
            return None
        if row.get("tenant_id") != self._tenant_id:
            return None
        if self._user_id is not None and row.get("user_id") not in (None, self._user_id):
            return None
        if self._enforce_application and row.get("application_id") not in (None, self._application_id):
            return None
        return row

    async def append(self, message: Message) -> Message:
        if self._user_id is None:
            raise ValueError("追加消息缺少 user_id")
        # 跨租户写入保护：若会话已存在，必须归属当前作用域；不存在则放行
        # （chat_service 在 create_conversation 之后紧接着 append 第一条消息，
        #  此时会话刚写入事务可见性可能有差异；严格阻断会影响主流程）。
        conv_row = self._repo.get_conversation(message.conversation_id)
        if conv_row is not None:
            if conv_row.get("tenant_id") != self._tenant_id:
                raise ValueError("会话不属于当前租户")
            if self._user_id is not None and conv_row.get("user_id") not in (None, self._user_id):
                raise ValueError("会话不属于当前用户")
            if self._enforce_application and conv_row.get("application_id") not in (None, self._application_id):
                raise ValueError("会话不属于当前应用")
        tool_calls = [
            {"call_id": tc.call_id, "name": tc.name, "arguments": tc.arguments}
            for tc in message.tool_calls
        ]
        mid = self._repo.append_message(
            conversation_id=message.conversation_id,
            tenant_id=self._tenant_id,
            user_id=self._user_id,
            application_id=self._application_id,
            role=message.role,
            content=message.content,
            tool_calls=tool_calls or None,
            tool_call_id=message.tool_call_id,
            tool_name=message.name,
            run_id=self._run_id,
            metadata=message.metadata,
        )
        return Message(
            message_id=mid,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            name=message.name,
            created_at=datetime.now(timezone.utc),
            metadata=message.metadata,
        )

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int = 100,
    ) -> list[Message]:
        # 跨租户/跨应用访问保护：先查会话归属，绑定的 tenant_id 不匹配时直接返回空，
        # 防止上游节点 config 里被填成别人的 conversation_id 造成 IDOR 泄漏。
        row = self._assert_conversation_in_scope(conversation_id)
        if row is None:
            return []
        rows = self._repo.list_messages_by_conversation(
            conversation_id, limit=limit,
        )
        return [_row_to_message(r) for r in rows]

    async def delete(self, message_id: UUID) -> None:
        # 先查消息归属的会话，再校验会话作用域，防止删除别人会话里的消息
        msg_row = self._repo.get_message(message_id)
        if msg_row is None:
            return
        conv_id = msg_row.get("conversation_id")
        if conv_id and self._assert_conversation_in_scope(conv_id) is None:
            return
        self._repo.delete_message(message_id)

    async def clear(self, conversation_id: UUID) -> None:
        row = self._assert_conversation_in_scope(conversation_id)
        if row is None:
            return
        self._repo.clear_messages(conversation_id)
