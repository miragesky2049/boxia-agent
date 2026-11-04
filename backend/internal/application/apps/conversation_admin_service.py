"""admin 会话排查应用服务：会话/消息列表、删除与试运行建会话（DDD 五期从 router 下沉）。

仓储经 domain Protocol 端口注入；提交依赖收口为 `commit` 回调（组合根传
uow.commit），避免应用层再耦合 UnitOfWork 全量协议。只读方法不提交
（与迁移前 router 行为一致）。租户归属校验在服务层收口，
"调用方身份 → tenant_id" 的解析（显式参数优先）留在 web 边界。
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from internal.application.errors import NotFoundError
from internal.domain.repository.apps_protocols import (
    ConversationRepositoryProtocol,
    MessageRepositoryProtocol,
)


class ConversationAdminService:
    """平台管理员会话排查：按应用列会话、拉消息、删除；画布试运行建会话。"""

    def __init__(
        self,
        commit: Callable[[], None],
        conv_repo: ConversationRepositoryProtocol,
        msg_repo: MessageRepositoryProtocol,
    ) -> None:
        self._commit = commit
        self._conv_repo = conv_repo
        self._msg_repo = msg_repo

    def create_debug_conversation(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        application_id: UUID,
        title: str,
    ) -> UUID:
        """画布对话流试运行建会话（channel=debug），创建即提交。"""
        conversation_id = self._conv_repo.insert_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            application_id=application_id,
            title=title,
            channel="debug",
        )
        self._commit()
        return conversation_id

    def list_app_conversations(
        self,
        *,
        tenant_id: UUID,
        application_id: UUID,
        limit: int,
        offset: int,
    ) -> list[dict]:
        """列出应用下的会话行（按最近活跃倒序，含所属用户）。"""
        return self._conv_repo.list_conversations_by_application(
            tenant_id=tenant_id,
            application_id=application_id,
            limit=limit,
            offset=offset,
        )

    def list_messages(self, *, conversation_id: UUID, tenant_id: UUID, limit: int) -> list[dict]:
        """拉取会话历史消息行（升序）；先校验会话归属租户。"""
        self._load_in_scope(conversation_id, tenant_id)
        return self._msg_repo.list_messages_by_conversation(conversation_id, limit=limit)

    def delete_conversation(self, *, conversation_id: UUID, tenant_id: UUID) -> None:
        """删除会话（消息由外键 ON DELETE CASCADE 清理）；先校验归属。"""
        self._load_in_scope(conversation_id, tenant_id)
        self._conv_repo.delete_conversation(conversation_id)
        self._commit()

    def delete_message(self, *, conversation_id: UUID, message_id: UUID, tenant_id: UUID) -> None:
        """删除会话内单条消息；会话归属 + 消息-会话一致性双重校验。"""
        self._load_in_scope(conversation_id, tenant_id)
        row = self._msg_repo.get_message(message_id)
        if row is None or row.get("conversation_id") != conversation_id:
            raise NotFoundError("消息不存在")
        self._msg_repo.delete_message(message_id)
        self._commit()

    def _load_in_scope(self, conversation_id: UUID, tenant_id: UUID) -> dict:
        """按租户校验会话归属，查不到或跨租户统一按不存在处理，避免暴露他人会话。"""
        row = self._conv_repo.get_conversation(conversation_id)
        if row is None or row.get("tenant_id") != tenant_id:
            raise NotFoundError("会话不存在")
        return row
