"""AsyncMessageRepository / AsyncConversationRepository 跨租户保护单测。

安全审查：LLM 节点 needHistory / CreateMessage / QueryConversationHistory 等从
config/inputs 取 conversation_id 直接读写消息，若被填成别人的 conversation_id
会造成 IDOR。Adapter 必须强制用绑定的 tenant_id/user_id/application_id 校验
会话归属。
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from internal.domain.agent.model import Message
from internal.infrastructure.repository.apps.async_conversation_adapter import (
    AsyncConversationRepository,
    AsyncMessageRepository,
)


class _FakeSyncRepo:
    """模拟 sync ConversationRepository + MessageRepository 的最小行为。"""

    def __init__(self, conversation_row: dict | None = None) -> None:
        self._conv = conversation_row
        self.list_called = False
        self.deleted_message_id: UUID | None = None
        self.cleared_conversation_id: UUID | None = None
        self.updated_title: tuple[UUID, str] | None = None
        self.deleted_conversation_id: UUID | None = None
        self.appended: list[dict] = []
        self.message_row: dict | None = None

    def get_conversation(self, conversation_id: UUID) -> dict | None:
        return self._conv

    def list_messages_by_conversation(
        self, conversation_id: UUID, *, limit: int = 50
    ) -> list[dict]:
        self.list_called = True
        return []

    def get_message(self, message_id: UUID) -> dict | None:
        return self.message_row

    def delete_message(self, message_id: UUID) -> None:
        self.deleted_message_id = message_id

    def clear_messages(self, conversation_id: UUID) -> None:
        self.cleared_conversation_id = conversation_id

    def update_title(self, conversation_id: UUID, title: str) -> None:
        self.updated_title = (conversation_id, title)

    def delete_conversation(self, conversation_id: UUID) -> None:
        self.deleted_conversation_id = conversation_id

    def append_message(self, **kwargs) -> UUID:
        self.appended.append(kwargs)
        return uuid4()


def _msg_adapter(
    *, tenant_id: UUID, user_id: UUID | None, application_id: UUID, conv_row: dict | None
) -> AsyncMessageRepository:
    fake = _FakeSyncRepo(conv_row)
    return AsyncMessageRepository(
        fake,
        tenant_id=tenant_id,
        user_id=user_id,
        application_id=application_id,
        conversation_repo=fake,
    )


def _conv_adapter(
    *, tenant_id: UUID, user_id: UUID | None, application_id: UUID, conv_row: dict | None
) -> AsyncConversationRepository:
    return AsyncConversationRepository(
        _FakeSyncRepo(conv_row),
        tenant_id=tenant_id,
        user_id=user_id,
        application_id=application_id,
    )


# ========== list_by_conversation ==========
def test_list_by_conversation_returns_messages_when_scope_matches() -> None:
    tenant_id, user_id, app_id, conv_id = uuid4(), uuid4(), uuid4(), uuid4()
    conv_row = {"id": conv_id, "tenant_id": tenant_id, "user_id": user_id, "application_id": app_id}
    repo = _msg_adapter(
        tenant_id=tenant_id, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    result = asyncio.run(repo.list_by_conversation(conv_id))
    assert result == []
    assert repo._repo.list_called is True


def test_list_by_conversation_rejects_cross_tenant() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _msg_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    result = asyncio.run(repo.list_by_conversation(conv_id))
    assert result == []
    assert repo._repo.list_called is False


# ========== append ==========
def test_append_rejects_cross_tenant_conversation() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _msg_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    msg = Message(message_id=uuid4(), conversation_id=conv_id, role="user", content="hi")
    with pytest.raises(ValueError, match="租户"):
        asyncio.run(repo.append(msg))
    assert repo._repo.appended == []


def test_append_allows_when_conversation_missing() -> None:
    # 会话刚创建尚未落库的兜底场景：conv_row=None 时放行 append（不抛错）
    tenant_id, user_id, app_id = uuid4(), uuid4(), uuid4()
    repo = _msg_adapter(tenant_id=tenant_id, user_id=user_id, application_id=app_id, conv_row=None)
    msg = Message(message_id=uuid4(), conversation_id=uuid4(), role="user", content="hi")
    asyncio.run(repo.append(msg))
    assert len(repo._repo.appended) == 1


# ========== delete_message ==========
def test_delete_message_rejects_cross_owner() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    msg_id = uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _msg_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    repo._repo.message_row = {"id": msg_id, "conversation_id": conv_id}
    asyncio.run(repo.delete(msg_id))
    assert repo._repo.deleted_message_id is None


def test_delete_message_allows_when_owner() -> None:
    tenant_id, user_id, app_id, conv_id, msg_id = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    conv_row = {"id": conv_id, "tenant_id": tenant_id, "user_id": user_id, "application_id": app_id}
    repo = _msg_adapter(
        tenant_id=tenant_id, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    repo._repo.message_row = {"id": msg_id, "conversation_id": conv_id}
    asyncio.run(repo.delete(msg_id))
    assert repo._repo.deleted_message_id == msg_id


# ========== clear ==========
def test_clear_rejects_cross_tenant() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _msg_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    asyncio.run(repo.clear(conv_id))
    assert repo._repo.cleared_conversation_id is None


# ========== AsyncConversationRepository get/delete/update_title ==========
def test_conv_get_rejects_cross_tenant() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _conv_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    result = asyncio.run(repo.get(conv_id))
    assert result is None


def test_conv_delete_rejects_cross_tenant() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _conv_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    asyncio.run(repo.delete(conv_id))
    assert repo._repo.deleted_conversation_id is None


def test_conv_update_title_rejects_cross_tenant() -> None:
    bound_tenant, other_tenant = uuid4(), uuid4()
    user_id, app_id, conv_id = uuid4(), uuid4(), uuid4()
    conv_row = {
        "id": conv_id,
        "tenant_id": other_tenant,
        "user_id": user_id,
        "application_id": app_id,
    }
    repo = _conv_adapter(
        tenant_id=bound_tenant, user_id=user_id, application_id=app_id, conv_row=conv_row
    )
    asyncio.run(repo.update_title(conv_id, "new title"))
    assert repo._repo.updated_title is None
