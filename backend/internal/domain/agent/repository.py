"""Conversation / Message 仓储抽象接口。

节点 handler 与 Agent 循环只依赖本接口，不直接操作数据库。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from internal.domain.agent.model import Conversation, Message


class ConversationRepository(ABC):
    """会话仓储。"""

    @abstractmethod
    async def create(self, conversation: Conversation) -> Conversation:
        """创建会话。"""

    @abstractmethod
    async def get(self, conversation_id: UUID) -> Conversation | None:
        """按 ID 查会话。"""

    @abstractmethod
    async def list_by_user(
        self,
        tenant_id: UUID,
        user_id: UUID,
        app_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Conversation]:
        """列出某用户的会话列表（按 updated_at 倒序）。"""

    @abstractmethod
    async def delete(self, conversation_id: UUID) -> None:
        """删除会话（级联删除消息）。"""

    @abstractmethod
    async def clear_summary(self, conversation_id: UUID) -> None:
        """清空摘要式记忆的摘要正文与水位线（M4 PRD F15.7：清空上下文时联动调用）。"""

    @abstractmethod
    async def update_title(self, conversation_id: UUID, title: str) -> None:
        """更新会话标题。"""


class MessageRepository(ABC):
    """消息仓储。"""

    @abstractmethod
    async def append(self, message: Message) -> Message:
        """追加一条消息。"""

    @abstractmethod
    async def list_by_conversation(
        self,
        conversation_id: UUID,
        limit: int = 100,
    ) -> list[Message]:
        """拉取会话历史消息（按 created_at 升序）。"""

    @abstractmethod
    async def delete(self, message_id: UUID) -> None:
        """删除单条消息。"""

    @abstractmethod
    async def clear(self, conversation_id: UUID) -> None:
        """清空会话所有消息。"""
