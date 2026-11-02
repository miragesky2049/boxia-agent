"""意图识别节点（type=22）测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.intent import (
    IntentNodeHandler,
    _extract_id,
    _parse_intents,
)


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def chat(self, *, messages, model, temperature=0.0):
        self.calls.append({"messages": messages, "model": model, "temperature": temperature})
        return SimpleNamespace(content=self.content)


class _FakeMessageRepo:
    def __init__(self) -> None:
        self.messages = [
            SimpleNamespace(role="user", content="我想查订单"),
            SimpleNamespace(role="assistant", content="请提供订单号"),
            SimpleNamespace(role="tool", content="should be filtered"),
        ]

    async def list_by_conversation(self, conversation_id, limit=10):
        return self.messages[:limit]


def _make_ctx(config: dict, services: ServiceRegistry | None = None, conversation_id=None) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="intent-test",
        application_id=uuid4(),
        conversation_id=conversation_id,
        system={"USER_INPUT": "我想查订单"},
    )
    return NodeContext(
        node_id="intent_1",
        node_type=NodeType.INTENT.value,
        inputs={},
        config=config,
        env=env,
        services=services or ServiceRegistry(),
    )


INTENTS = [
    {"id": 1, "name": "查订单", "description": "查询订单状态"},
    {"id": 2, "name": "退款", "description": "申请退款"},
]


def test_parse_intents_normalizes_ids_and_dedupes() -> None:
    parsed = _parse_intents([
        {"name": "A"},
        {"id": 1, "name": "B"},
        "C",
        {"id": 0, "name": "D"},
        {"name": ""},
    ])
    assert [item["id"] for item in parsed] == [1, 2, 3, 4]
    assert [item["name"] for item in parsed] == ["A", "B", "C", "D"]


def test_extract_id_accepts_json_and_plain_number() -> None:
    assert _extract_id('{"classification_id": 2}', {1, 2}) == 2
    assert _extract_id("1", {1, 2}) == 1
    assert _extract_id('{"classification_id": 9}', {1, 2}) is None


def test_llm_classification_routes_by_id() -> None:
    llm = _FakeLLM('{"classification_id": 2}')
    result = asyncio.run(
        IntentNodeHandler().run(
            _make_ctx(
                {"intents": INTENTS, "modleName": "m-1"},
                ServiceRegistry({"llm": llm}),
            )
        )
    )
    assert result.route == "2"
    assert result.outputs["classificationId"] == 2
    assert result.outputs["classificationName"] == "退款"
    assert result.outputs["query"] == "我想查订单"
    assert llm.calls[0]["model"] == "m-1"
    assert llm.calls[0]["temperature"] == 0.0
    assert "1. 查订单" in llm.calls[0]["messages"][0]["content"]


def test_llm_invalid_output_falls_to_other() -> None:
    result = asyncio.run(
        IntentNodeHandler().run(
            _make_ctx(
                {"intents": INTENTS, "modleName": "m-1"},
                ServiceRegistry({"llm": _FakeLLM("不确定")}),
            )
        )
    )
    assert result.route == "0"
    assert result.outputs["classificationId"] == 0
    assert result.outputs["classificationName"] == "其他"


def test_llm_failure_keeps_flow_alive_with_error() -> None:
    class _BrokenLLM:
        async def chat(self, **_kwargs):
            raise RuntimeError("provider down")

    result = asyncio.run(
        IntentNodeHandler().run(
            _make_ctx(
                {"intents": INTENTS, "modleName": "m-1"},
                ServiceRegistry({"llm": _BrokenLLM()}),
            )
        )
    )
    assert result.route == "0"
    assert "provider down" in result.outputs["error"]


def test_without_model_uses_keyword_fallback() -> None:
    result = asyncio.run(
        IntentNodeHandler().run(_make_ctx({"intents": INTENTS}, ServiceRegistry()))
    )
    assert result.route == "1"
    assert result.outputs["classificationName"] == "查订单"


def test_empty_intents_returns_other() -> None:
    result = asyncio.run(IntentNodeHandler().run(_make_ctx({"intents": []})))
    assert result.route == "0"
    assert result.outputs["query"] == "我想查订单"


def test_query_prefers_node_inputs() -> None:
    ctx = _make_ctx({"intents": INTENTS}, ServiceRegistry())
    ctx = NodeContext(
        node_id=ctx.node_id,
        node_type=ctx.node_type,
        inputs={"query": "帮我退款"},
        config=ctx.config,
        env=ctx.env,
        services=ctx.services,
    )
    result = asyncio.run(IntentNodeHandler().run(ctx))
    assert result.route == "2"


def test_need_history_appends_conversation_messages() -> None:
    llm = _FakeLLM('{"classification_id": 1}')
    result = asyncio.run(
        IntentNodeHandler().run(
            _make_ctx(
                {"intents": INTENTS, "modleName": "m-1", "needHistory": True},
                ServiceRegistry({"llm": llm, "message_repo": _FakeMessageRepo()}),
                conversation_id=uuid4(),
            )
        )
    )
    messages = llm.calls[0]["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert result.route == "1"
