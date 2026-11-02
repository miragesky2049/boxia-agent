"""T5: LLM 节点流式输出单测。

验证：
- 无 tools + ctx.emit_event 可用时，走 chat_stream 路径
- 每个 delta chunk 触发一次 llm_token 事件
- 最终 outputs["output"] 是所有 delta 聚合
- usage 从收尾 chunk 回灌
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator
from uuid import uuid4

from internal.domain.canvas.node_type import NodeType
from internal.domain.graph.node_base import NodeContext, RuntimeEnv, ServiceRegistry
from internal.domain.graph.nodes.llm import LLMNodeHandler
from internal.domain.llm.client import LLMResponse, LLMUsage


class _Chunk:
    def __init__(
        self,
        content: str = "",
        finish_reason: str = "stop",
        usage: LLMUsage | None = None,
    ) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.usage = usage or LLMUsage()
        self.tool_calls: list[Any] = []
        self.model = "test-model"


class _StreamingLLM:
    """mock：返回 ["你", "好", "，", "boxia"] 四个增量 + 一个收尾空 chunk。"""

    def __init__(self) -> None:
        self.chat_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def chat(self, **kwargs) -> LLMResponse:
        self.chat_calls.append(kwargs)
        return LLMResponse(content="应走流式路径，不应调用 chat", model="test-model")

    async def chat_stream(
        self,
        *,
        messages: list[dict],
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> AsyncIterator[LLMResponse]:
        self.stream_calls.append({
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        for delta in ["你", "好", "，", "boxia"]:
            yield LLMResponse(content=delta, finish_reason="stop", model=model)
        yield LLMResponse(
            content="",
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            model=model,
        )


def _make_ctx(services: ServiceRegistry, config: dict, emit_event=None) -> NodeContext:
    env = RuntimeEnv(
        tenant_id=uuid4(),
        user_id=None,
        run_id=uuid4(),
        thread_id="test-thread",
        application_id=uuid4(),
    )
    return NodeContext(
        node_id="llm_1",
        node_type=NodeType.LLM.value,
        inputs={"input": "介绍一下你自己"},
        config=config,
        env=env,
        services=services,
        emit_event=emit_event,
    )


def test_llm_node_streaming_emits_tokens_and_aggregates_output() -> None:
    events: list[tuple[str, dict]] = []

    async def _emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    mock_llm = _StreamingLLM()
    services = ServiceRegistry({"llm": mock_llm})

    ctx = _make_ctx(
        services,
        config={
            "modleName": "test-model",
            "prompt": "{{input}}",
            "temperature": 0.5,
        },
        emit_event=_emit,
    )

    result = asyncio.run(LLMNodeHandler().run(ctx))

    # 流式路径：不调用 chat，只调用 chat_stream
    assert mock_llm.chat_calls == []
    assert len(mock_llm.stream_calls) == 1
    assert mock_llm.stream_calls[0]["model"] == "test-model"
    assert mock_llm.stream_calls[0]["temperature"] == 0.5

    # 4 个 llm_token 事件
    token_events = [e for e in events if e[0] == "llm_token"]
    assert [e[1]["delta"] for e in token_events] == ["你", "好", "，", "boxia"]
    assert all(e[1]["node_id"] == "llm_1" for e in token_events)

    # 最终输出聚合
    assert result.outputs["output"] == "你好，boxia"

    # usage 从收尾 chunk 回灌
    assert result.usage == {
        "prompt_tokens": 10,
        "completion_tokens": 8,
        "total_tokens": 18,
    }


def test_llm_node_streaming_collects_reasoning_content() -> None:
    events: list[tuple[str, dict]] = []

    async def _emit(event_type: str, payload: dict) -> None:
        events.append((event_type, payload))

    class _ReasoningLLM:
        async def chat_stream(self, *, messages, model, **kwargs):
            yield LLMResponse(content="", reasoning_content="先分析", model=model)
            yield LLMResponse(content="", reasoning_content="再回答", model=model)
            yield LLMResponse(content="最终答案", finish_reason="stop", model=model)

    ctx = _make_ctx(
        ServiceRegistry({"llm": _ReasoningLLM()}),
        config={"modleName": "test-model", "prompt": "{{input}}"},
        emit_event=_emit,
    )

    result = asyncio.run(LLMNodeHandler().run(ctx))

    assert result.outputs["output"] == "最终答案"
    assert result.outputs["reasoning_content"] == "先分析再回答"
    assert [e[1]["delta"] for e in events if e[0] == "llm_token"] == ["最终答案"]


def test_llm_node_stream_false_uses_chat_and_outputs_reasoning() -> None:
    class _NonStreamingReasoningLLM:
        def __init__(self) -> None:
            self.chat_calls = 0

        async def chat(self, **kwargs) -> LLMResponse:
            self.chat_calls += 1
            return LLMResponse(
                content="非流式回复",
                reasoning_content="非流式思考",
                model="test-model",
            )

    mock = _NonStreamingReasoningLLM()
    ctx = _make_ctx(
        ServiceRegistry({"llm": mock}),
        config={
            "modleName": "test-model",
            "prompt": "{{input}}",
            "stream": False,
        },
        emit_event=lambda et, p: asyncio.sleep(0),
    )

    result = asyncio.run(LLMNodeHandler().run(ctx))

    assert mock.chat_calls == 1
    assert result.outputs["output"] == "非流式回复"
    assert result.outputs["reasoning_content"] == "非流式思考"


def test_llm_node_falls_back_to_chat_when_no_emit_event() -> None:
    """无 emit_event 通道时，即使无 tools 也走非流式 chat 路径。"""

    class _NonStreamingLLM:
        def __init__(self) -> None:
            self.chat_calls = 0
            self.stream_calls = 0

        async def chat(self, **kwargs) -> LLMResponse:
            self.chat_calls += 1
            return LLMResponse(
                content="非流式完整回复",
                usage=LLMUsage(prompt_tokens=5, completion_tokens=6, total_tokens=11),
                model="test-model",
            )

        async def chat_stream(self, **kwargs) -> AsyncIterator[LLMResponse]:
            self.stream_calls += 1
            yield LLMResponse(content="不应走到这里", model="test-model")

    mock = _NonStreamingLLM()
    services = ServiceRegistry({"llm": mock})

    # 不传 emit_event
    ctx = _make_ctx(
        services,
        config={"modleName": "test-model", "prompt": "{{input}}"},
        emit_event=None,
    )

    result = asyncio.run(LLMNodeHandler().run(ctx))
    assert result.outputs["output"] == "非流式完整回复"
    assert mock.chat_calls == 1
    assert mock.stream_calls == 0
