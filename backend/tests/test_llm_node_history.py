"""T6: LLM 节点 needHistory 记忆开关单测。

验证：
- needHistory=false 时不查 message_repo
- needHistory=true 时把 conversation_id 对应的历史 user/assistant 消息拼进 messages
- 历史消息过滤掉 system/tool 等非 user/assistant 角色
- conversation_id 缺失或非法时静默跳过，不抛错
- message_repo 未注册时静默跳过
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.llm import LLMNodeHandler
from internal.engine.llm import LLMResponse, LLMUsage


class _Msg:
    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class _FakeMessageRepo:
    def __init__(self, rows: list[_Msg]) -> None:
        self._rows = rows
        self.calls: list[dict[str, Any]] = []

    async def list_by_conversation(self, conversation_id: UUID, limit: int = 100) -> list[_Msg]:
        self.calls.append({"conversation_id": str(conversation_id), "limit": limit})
        return self._rows


class _CapturingLLM:
    """非流式 chat：把收到的 messages 抓下来供断言。"""

    def __init__(self) -> None:
        self.seen_messages: list[list[dict[str, Any]]] = []

    async def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        tools: list | None = None,
    ) -> LLMResponse:
        self.seen_messages.append(list(messages))
        return LLMResponse(
            content="最终答复",
            usage=LLMUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
            model=model,
        )


def _make_ctx(
    services: ServiceRegistry,
    config: dict,
    inputs: dict | None = None,
) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=uuid4(),
        run_id=uuid4(),
        thread_id="test-thread",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="llm_1",
        node_type=NodeType.LLM.value,
        inputs=inputs or {"input": "当前问题"},
        config=config,
        env=env,
        services=services,
    )


def _base_config() -> dict:
    return {
        "modleName": "test-model",
        "prompt": "{{input}}",
        "temperature": 0.5,
    }


def test_need_history_false_does_not_query_message_repo() -> None:
    repo = _FakeMessageRepo([_Msg("user", "hi")])
    llm = _CapturingLLM()
    services = ServiceRegistry({"llm": llm, "message_repo": repo})

    cfg = _base_config()
    cfg["needHistory"] = False
    cfg["conversation_id"] = str(uuid4())

    ctx = _make_ctx(services, cfg)
    asyncio.run(LLMNodeHandler().run(ctx))

    assert repo.calls == []
    # 只有 system（空）+ 当前 user 消息
    assert len(llm.seen_messages) == 1
    assert llm.seen_messages[0] == [{"role": "user", "content": "当前问题"}]


def test_need_history_true_prepends_user_assistant_messages() -> None:
    conv_id = uuid4()
    rows = [
        _Msg("user", "你好"),
        _Msg("assistant", "你好，有什么可以帮你"),
        _Msg("system", "不该出现"),  # 过滤
        _Msg("tool", "工具结果"),  # 过滤
        _Msg("user", "第二个问题"),
        _Msg("assistant", "第二个回答"),
    ]
    repo = _FakeMessageRepo(rows)
    llm = _CapturingLLM()
    services = ServiceRegistry({"llm": llm, "message_repo": repo})

    cfg = _base_config()
    cfg["needHistory"] = True
    cfg["historyLimit"] = 10

    ctx = _make_ctx(services, cfg, inputs={"input": "当前问题", "conversation_id": str(conv_id)})
    asyncio.run(LLMNodeHandler().run(ctx))

    assert len(repo.calls) == 1
    assert repo.calls[0]["conversation_id"] == str(conv_id)
    assert repo.calls[0]["limit"] == 10

    msgs = llm.seen_messages[0]
    # 应该是：4 条历史 user/assistant + 当前 user
    assert [m["role"] for m in msgs] == [
        "user", "assistant", "user", "assistant", "user",
    ]
    assert msgs[0]["content"] == "你好"
    assert msgs[1]["content"] == "你好，有什么可以帮你"
    assert msgs[2]["content"] == "第二个问题"
    assert msgs[3]["content"] == "第二个回答"
    assert msgs[4]["content"] == "当前问题"


def test_need_history_missing_conversation_id_skips_silently() -> None:
    repo = _FakeMessageRepo([_Msg("user", "hi")])
    llm = _CapturingLLM()
    services = ServiceRegistry({"llm": llm, "message_repo": repo})

    cfg = _base_config()
    cfg["needHistory"] = True
    # 不设置 conversation_id

    ctx = _make_ctx(services, cfg)
    asyncio.run(LLMNodeHandler().run(ctx))

    assert repo.calls == []
    assert llm.seen_messages[0] == [{"role": "user", "content": "当前问题"}]


def test_need_history_invalid_conversation_id_skips_silently() -> None:
    repo = _FakeMessageRepo([_Msg("user", "hi")])
    llm = _CapturingLLM()
    services = ServiceRegistry({"llm": llm, "message_repo": repo})

    cfg = _base_config()
    cfg["needHistory"] = True

    ctx = _make_ctx(
        services, cfg,
        inputs={"input": "当前问题", "conversation_id": "not-a-uuid"},
    )
    asyncio.run(LLMNodeHandler().run(ctx))

    assert repo.calls == []


def test_need_history_no_message_repo_registered_skips() -> None:
    llm = _CapturingLLM()
    services = ServiceRegistry({"llm": llm})  # 没有 message_repo

    cfg = _base_config()
    cfg["needHistory"] = True
    cfg["conversation_id"] = str(uuid4())

    ctx = _make_ctx(services, cfg)
    asyncio.run(LLMNodeHandler().run(ctx))

    assert llm.seen_messages[0] == [{"role": "user", "content": "当前问题"}]
