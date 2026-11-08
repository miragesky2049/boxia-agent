"""会话节点 conversation_id 上下文回退测试。

覆盖：对话流运行时未显式连线会话 ID 时，消息类节点回退到 RuntimeEnv.conversation_id；
两者都缺失时抛出可读错误，而不是把 error 写进 outputs 让下游误用。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.conversation_nodes import (
    ClearContextNodeHandler,
    CreateMessageNodeHandler,
)


def _make_env(conversation_id=None) -> RuntimeEnv:
    return RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="conv-test",
        application_id=uuid4(),
        conversation_id=conversation_id,
    )


class _FakeMessageRepo:
    def __init__(self) -> None:
        self.appended = []
        self.cleared = []

    async def append(self, message):
        self.appended.append(message)
        return replace(message, message_id=uuid4())

    async def clear(self, conversation_id):
        self.cleared.append(conversation_id)


def test_create_message_falls_back_to_runtime_conversation():
    conv_id = uuid4()
    repo = _FakeMessageRepo()
    ctx = NodeContext(
        node_id="msg_1",
        node_type="55",
        inputs={"content": "hello"},
        config={"role": "assistant"},
        env=_make_env(conversation_id=conv_id),
        services=ServiceRegistry({"message_repo": repo}),
    )

    result = asyncio.run(CreateMessageNodeHandler().run(ctx))

    assert repo.appended[0].conversation_id == conv_id
    assert "message_id" in result.outputs


def test_create_message_prefers_explicit_input_over_context():
    explicit = uuid4()
    ctx = NodeContext(
        node_id="msg_1",
        node_type="55",
        inputs={"conversation_id": str(explicit), "content": "hi"},
        config={},
        env=_make_env(conversation_id=uuid4()),
        services=ServiceRegistry({"message_repo": _FakeMessageRepo()}),
    )

    asyncio.run(CreateMessageNodeHandler().run(ctx))


def test_create_message_without_conversation_raises_readable_error():
    ctx = NodeContext(
        node_id="msg_1",
        node_type="55",
        inputs={"content": "hi"},
        config={},
        env=_make_env(),
        services=ServiceRegistry({"message_repo": _FakeMessageRepo()}),
    )

    with pytest.raises(ValueError, match="缺少 conversation_id"):
        asyncio.run(CreateMessageNodeHandler().run(ctx))


def test_clear_context_uses_runtime_conversation():
    conv_id = uuid4()
    repo = _FakeMessageRepo()
    ctx = NodeContext(
        node_id="clear_1",
        node_type="38",
        inputs={},
        config={},
        env=_make_env(conversation_id=conv_id),
        services=ServiceRegistry({"message_repo": repo}),
    )

    asyncio.run(ClearContextNodeHandler().run(ctx))

    assert repo.cleared == [conv_id]


class _FakeConvRepo:
    def __init__(self) -> None:
        self.summary_cleared = []

    async def clear_summary(self, conversation_id):
        self.summary_cleared.append(conversation_id)


def test_clear_context_also_invalidates_summary():
    """M4 PRD F15.7：清空上下文联动清摘要与水位线，防"清完还带着旧摘要对话"。"""
    conv_id = uuid4()
    msg_repo = _FakeMessageRepo()
    conv_repo = _FakeConvRepo()
    ctx = NodeContext(
        node_id="clear_1",
        node_type="38",
        inputs={},
        config={},
        env=_make_env(conversation_id=conv_id),
        services=ServiceRegistry({"message_repo": msg_repo, "conversation_repo": conv_repo}),
    )

    asyncio.run(ClearContextNodeHandler().run(ctx))

    assert msg_repo.cleared == [conv_id]
    assert conv_repo.summary_cleared == [conv_id]
